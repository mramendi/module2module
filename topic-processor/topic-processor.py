#!/usr/bin/python3

# prerequisites:
# - lxml (on Fedora, available from dnf as python3-lxml) for XML processing
#      IMPORATNT: the code relies on the lxml behaviour of a child element being moved,
#        not copied, when added to a new parent
# - thefuzz (pip install thefuzz) for fuzzy string comparisons (so typos don't prevent procedure parsing)

from lxml import etree
from thefuzz import fuzz
from pathlib import Path
import sys
import os.path

# The threshold for fuzzy string comparison (the fuzz ratio must be GREATER THAN this threshold for a match)
# Make this higher if unrelated titles get interpreterd as Procedure, Prerequisites etc
fuzz_threshold = 80

# the unprocessed "dump" element - all elements that we need to skip will be moved here
unprocessed_dump = etree.Element("unprocessed")


permitted_tags_shortdesc = [  "ph","codeph","synph","filepath","msgph","userinput","systemoutput","b","u","i","tt","sup","sub","uicontrol","menucascade","term","q","boolean","state","keyword","option","parmname","apiname","cmdname","msgnum","varname","wintitle","tm","image","data","data-about","foreign","unknown" ]

permitted_tags_cmd = [ "boolean","cite","keyword","apiname","option","parmname","cmdname","msgnum","varname","wintitle","ph","b","i","sup","sub","tt","u","codeph","synph","filepath","msgph","systemoutput","userinput","menucascade","uicontrol","q","term","abbreviated-form","tm","xref","state","data","data-about","foreign","unknown","image","draft-comment","fn","indextermref","indexterm","required-cleanup" ]

def error(message):
    """log an error and exit"""
    print("ERROR: ",message)
    sys.exit(1)

def warning(message):
    """log a warning and continue"""
    print("WARNING: ",message)

def gettext(elem,strip=True):
    """get the entire text content of an element including that in subelements

    Used for parsing titles, so strips spaces/newlines at the start and end by default"""
    r = ''.join(elem.itertext())
    if strip:
        r = r.strip()
    return r

def unprocess(elem, text=""):
    """log an element that was not processed and move it into the dump"""
    parent=elem.getparent()
    if parent is None:
        warning(f"Unprocessed element <{elem.tag}> in an undetected parent")
    else:
        warning(f"Unprocessed element <{elem.tag}> in parent <{parent.tag}>")
    unprocessed_dump.append(elem)



def check_tags_valid(elem,permitted_tags):
    """Check if all tags inside the element are valid.

    Check that all immediate child tags of the element (not the element itself)
    are in the list of permitted tags. True if they are, False if a
    non-permitted tag is found. Absence of any child tags would mean True"""

    for child in elem:
        if not (child.tag in permitted_tags):
            return False
    return True

def unprocess_children_until(elem,target_tags):
    """ 'Unprocess' child tags until one of the target tags is reached

        Returns True if elem[0] is now one of the target tags, False if elem has no more children
    """
    while (len(elem)>0) and not (elem[0].tag in target_tags):
        unprocess(elem[0])
    return (len(elem)>0)


def flatten_divs(elem):
    """ Find all div subelements directly inside an element and move contents into the element removing the divs
    """

    # I was not yet able to find a way to determine the index of a child after using find()
    # so here is a search loop - might change if I find the way

    while True:
        index = None
        found = None
        for i in range(len(elem)):
            if elem[i].tag =="div":
                found = elem[i]
                index = i
                break
        if found is None:
            break

        offset = 0
        while len(found) > 0:
            elem.insert(index+offset,found[0])
            offset+=1
        elem.remove(found)




def process_procedure(in_root):

    # anything with sections cannot be a procedure
    if in_root.find(".//section") is not None:
        error("<section> exists - cannot process as a procedure")

    # create the new root and the corresponding tree
    root = etree.XML(b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd"><task/>')
    tree = etree.ElementTree(root)

    # spot check - is this a topic at all?
    if in_root.tag!="topic":
        error("root tag is not a <topic>")

    # process the ID attribute
    root_id = in_root.get("id")
    if root_id is not None:
        root.set("id",root_id)

    # find the title
    if not unprocess_children_until(in_root,["title"]):
        error("<title> not found in topic")

    # move the title to the task
    root.append(in_root[0])

    abstract = etree.Element("abstract")
    root.append(abstract)

    # find the body or shortdesc
    if not unprocess_children_until(in_root,["shortdesc","body"]):
        error("<body> not found in topic")

    # if a shortdesc was found, process it then find the body
    if in_root[0].tag == "shortdesc":
        abstract.append(in_root[0])
        if not unprocess_children_until(in_root,["body"]):
            error("<body> not found in topic")

    in_body=in_root[0]

    # spot check
    if in_body.tag != "body":
        error("body is not <body> - this should never happen")
    if len(in_body) == 0:
        error("empty <body>")

    flatten_divs(in_body)


    # process first <p> into shortdesc if there is no shortdesc and the first element is <p>
    # Currently, role=abstract is not considered, instead we just check if all
    # tags inside the <p> are calid for <shortdesc>

    if in_body.find(".//shortdesc") is None:
        candidate_shortdesc = in_body[0]
        if (candidate_shortdesc.tag == "p") and check_tags_valid(candidate_shortdesc,permitted_tags_shortdesc):
            candidate_shortdesc.tag="shortdesc"
            abstract.append(candidate_shortdesc)




    # These variables will hold the context, prereq, steps, result, related-links elements,
    # As not all elements are in every task, an element is created the first time it is necessary
    # We fail if steps is not created
    prereq = None
    steps = None
    result = None
    related_links = None

    # process everything into abstract until a prerequisites or procedure header is found
    # IMPORTANT: this loop relies on the first element of in_body being taken out each time
    # If it cannot be processed we must take it out into unprocessed to avoid an endless loop
    # the loop itself just checks for exhaustion of elements; other checks work through break statements
    while len(in_body)>0:
        elem = in_body[0]

        # check if we have reached a prerequisites or procedure header
        if elem.tag == "p":
            if elem.get("outputclass") == "title":
                elemtext=gettext(elem)
                if fuzz.ratio(elemtext,"Procedure") > fuzz_threshold:
                    break
                if fuzz.ratio(elemtext,"Prerequisites") > fuzz_threshold:
                    break

        # if we are here we need to add the top element of the body to the abstract
        abstract.append(elem)

    if len(in_body) == 0:
        error("Procedure header not found")

    # create the taskbody and place it in its place
    body = etree.Element("taskbody")
    root.append(body)


    # at this point the first element is either the prerequisites header or the procerdure header
    # if it is the prerequisites header, process prerequisites and search for procedure
    elemtext = gettext(in_body[0])
    if fuzz.ratio(elemtext,"Prerequisites") > fuzz_threshold:

        # remove the title itself
        in_body.remove(in_body[0])

        # IMPORTANT: this loop relies on the first element of in_body being taken out each time
        # If it cannot be processed we must take it out into unprocessed to avoid an endless loop
        # the loop itself just checks for exhaustion of elements; other checks work through break statements
        while len(in_body)>0:
            elem = in_body[0]

            # check if we have reached a procedure header
            if elem.tag == "p":
                if elem.get("outputclass") == "title":
                    elemtext=gettext(elem)
                    if fuzz.ratio(elemtext,"Procedure") > fuzz_threshold:
                        break

            # if we are here we need to add the top element of the body to the prereq
            # but first, we create the prereq if it was not created yet
            if prereq is None:
                prereq = etree.Element("prereq")
                body.append(prereq)
            prereq.append(elem)

        if len(in_body) == 0:
            error("Procedure header not found")

    # at this point the first element of in_body is the procedure header
    # delete the header itself
    in_body.remove(in_body[0])


    # spot check: error out if no elements remain
    if len(in_body) == 0:
        error("Procedure header not found")


    # spot check: error out if no elements remain
    if len(in_body) == 0:
        error("Procedure header not found")

    # create the steps tag - we can retag to steps-unordered later if needed
    steps = etree.Element("steps")
    body.append(steps)

    # If we are not at <ol> or <ul> yet, push things into a stepsection until we are

    if not (in_body[0].tag in ["ol","ul"]):
        stepsection = etree.Element("stepsection")
        steps.append(stepsection)
        while len(in_body)>0:
            if in_body[0].tag in ["ol","ul"]:
                break
            stepsection.append(in_body[0])
        if len(in_body)==0:
            error("steps list not found")


    # At this point we are at <ol> or <ul>
    steps_list = in_body[0]
    if steps_list.tag == "ul":
        steps.tag = "steps-unordered"

    # Process all list entries
    for list_elem in steps_list:
        # spot check
        if list_elem.tag != "li":
            error("Non <li> element in step list")

        flatten_divs(list_elem)

        # create the <step>
        step = etree.Element("step")
        steps.append(step)

        # if the first child is <p> we want to move it whole - if we can
        # IMPORTANT: as this is a proof of concept, we error out if the <p> contains something disallowed in cmd
        # we also error out of the first child is not <p>, because in the existing converter it apparently always is?

        if list_elem[0].tag == "p" and check_tags_valid(list_elem[0],permitted_tags_cmd):
            list_elem[0].tag = "cmd"
            step.append(list_elem[0])
        else:
            error("List element not starting with <p> or not fitting for <cmd> conversion - FIX THIS SCRIPT")

        # if any other elements remain, move them to <info>
        # IMPORTANT: consider detecting patterns for <substeps>, <choices>. maybe even <stepxmp>
        if len(list_elem) > 0:
            info = etree.Element("info")
            step.append(info)
            while len(list_elem) > 0:
                info.append(list_elem[0])

    # At this point the entire list is processed (and is still the first element of in_body
    # Now we remove the list
    in_body.remove(in_body[0])


    # if elements still remain, we need to process any results and any additional resources
    # however anything except these things cannot be processed and has to be skipped

    while len(in_body)>0:
        elem = in_body[0]

        # check if we have reached a result or additional resources header
        if elem.tag == "p":
            if elem.get("outputclass") == "title":
                elemtext=gettext(elem)
                if fuzz.ratio(elemtext,"Result") > fuzz_threshold:
                    break
                if fuzz.ratio(elemtext,"Additional resources") > fuzz_threshold:
                    break
        unprocess(in_body[0])

    # we are either out of elements or at a title for result or additional resources
    # now we process the result if we are at the title for result
    if len(in_body) > 0:
        if fuzz.ratio(elemtext,"Result") > fuzz_threshold:
            # delete the title itself
            in_body.remove(in_body[0])

            # push everything into the <result> tag until either wein_body is empty
            #  or additional resources are found
            while len(in_body) > 0:
                elem = in_body [0]

                # check if we have reached an additional resources header
                if elem.tag == "p":
                    if elem.get("outputclass") == "title":
                        elemtext=gettext(elem)
                        if fuzz.ratio(elemtext,"Additional resources") > fuzz_threshold:
                            break

                # move the element into result, but first create result if it does not exist
                if result is None:
                    result = etree.Element("result")
                    body.append(result)
                result.append(elem)

    # we are either out of elements or at a title for result or additional resources
    if len(in_body) > 0:

        # spot check
        if fuzz.ratio(elemtext,"Additional resources") <= fuzz_threshold:
            error("Not at additional resources - this should not happen")
        else:
            # delete the title inself
            in_body.remove(in_body[0])

            # Find the <ul> that contains the additional resources list - skip everything else
            if not unprocess_children_until(in_body,"ul"):
                warning("Additional resources header found but list not found")
            else:
                for list_elem in in_body[0]:
                    # spot check
                    if list_elem.tag != "li":
                        error("Non <li> element in step list")

                    flatten_divs(list_elem)


                    # find the <xref> which is the only part we can process for now
                    while (len(list_elem)>0) and (list_elem[0].tag!="xref"):
                        warning("Unprocessed non-xref element in link list")
                        unprocess(list_elem[0])

                    # continue if the <li> is empty/xref not found
                    if len(list_elem)==0:
                        continue

                    xref = list_elem[0]

                    # create <related-links> if it does not exist
                    if related_links is None:
                        related_links = etree.Element("related-links")
                        root.append(related_links)

                    # create the <link>
                    link = etree.Element("link")
                    related_links.append(link)

                    # copy the href and scope attributes and remove them from the xref
                    link.set("href",xref.attrib.pop("href"))
                    if xref.get("scope"):
                        link.set("scope",xref.attrib.pop("scope"))

                    if gettext(xref)!="":
                        # convert the xref itself into linktext to preserve all text
                        xref.tag = "linktext"
                        link.append(xref)

        # after processing the additional resources list
        in_body.remove(in_body[0])

        while len(in_body)>0:
            unprocess(in_body[0])

    # processing is done
    return tree

def process_topic(in_file_name,out_file_name):
    in_xml = etree.parse(open(in_file_name,"r"))

    # determine the module type
    in_root = in_xml.getroot()
    in_class = in_root.get("outputclass")

    if in_class=="procedure":
        out_tree = process_procedure(in_root)
    else:
        error("class not processed currently: "+str(in_class))


    out_tree.write(out_file_name,xml_declaration = True)

if len(sys.argv) != 2:
    print(f"Convert DITA topic to specialization defined by outputclass - currently procedure only")
    print(f"Usage: {sys.argv[0]} file.dita")
    sys.exit(1)
Path("out").mkdir(exist_ok=True)
process_topic(sys.argv[1],os.path.join("out",sys.argv[1]))
