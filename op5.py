from urllib import quote, quote_plus
import requests #pip install requests
import json

from termcolor import colored #pip install termcolor
import time
import sys

import logging
logger = logging.getLogger("op5")

# This piece of code was mainly created by https://github.com/klarna/op5lib
# and adapted to SHKB's needs

# define a function for a yes no question to the user
# stolen from https://stackoverflow.com/questions/3041986/apt-command-line-interface-like-yes-no-input
def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = raw_input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

class NullHandler(logging.Handler):
    """
    For backward-compatibility with Python 2.6, a local class definition
    is used instead of logging.NullHandler
    """
    def handle(self, record):
        pass
    def emit(self, record):
        pass
    def createLock(self):
        self.lock = None

logger.addHandler(NullHandler())

class OP5(object):

    """
    Provides an abstraction layer for the op5 api.

    Attributes:
        api_url:                The url your op5 api is located at. Should be something like "https://op5.mydomain/api"
        api_username:           The username of a user that has permissions to use the api
        api_password:           Password that matches for the api_username
        dryrun:                 Only show what would be done but don't actually do it
        debug:                  Show some extra debug output
        interactive:            ?
        data:                   ?
        status_code:            ?
        logtofile:              ?
        max_retries:            How many times an api call should be retried
        retry_wait:             The period to wait between retries
        modified:               ?
        verify_certificates:    Verify the certificates delivered by your op5 api endpoint
    """

    # This will help create services
    # You will only have to assign values to:
    # check_command, check_command_args, host_name and service_description
    DEFAULT_SERVICE_DATA = {
        "check_command": "",
	"check_command_args": "",
	"check_interval": 2,
	"check_period": "24x7",
	"file_id": "etc/services.cfg",
	"host_name": "",
	"max_check_attempts": 3,
	"notification_interval": 0,
	"notification_options": [
	    "c",
	    "r",
	    "w"
	],
	"notification_period": "13x5",
	"retry_interval": 2,
	"service_description": "",
	"template": "default-service",
    }

    def __init__(self, api_url, api_username, api_password, dryrun=False, debug=False, logtofile=False, interactive=False, max_retries=3, retry_wait=6, verify_certificates=True):
        self.api_url = api_url
        self.api_username = api_username
        self.api_password = api_password
        self.dryrun = dryrun
        self.debug = debug
        self.interactive = interactive
        self.data = []
        self.status_code = -1
        self.logtofile = logtofile
        self.max_retries = max_retries
        self.retry_wait = retry_wait
        self.modified = False
        self.verify_certificates = verify_certificates


    def get_debug_text(self,request_type,object_type,name,data):
        #name will always be set except in the "create" case where everything is in "data"
        text = "%s(%s)" % (request_type,object_type)
        if name != "":
            text += " name: %s" % name
        if not data:
            return text

        #data exists
        if object_type in ["host","hostgroup","service"]:
            text += " ("
            interesting_fields = ["service_description","host_name","hostgroup_name","address","hostgroups","contact_groups","check_command","check_command_args"]
            available_fields = filter(lambda x: x in data, interesting_fields)
            text += ', '.join("%s='%s'" % (key,value) for key, value in [(field,data[field]) for field in available_fields])
            text += ")"
            return text
        elif object_type == "change":
            if request_type == "GET":
                return "Got list of changes"
            elif request_type == "POST":
                return "Commit saved"
            elif request_type == "DELETE":
                return "Changes removed"
        else: #for any other object type, print out a generic text
            return "%s(%s) data: %s" % (request_type,object_type,data)

    def command(self,command_type,query):
        """
        Submit an op5 command

        Parameters:
            command_type: Should be one of:
                * ACKNOWLEDGE_HOST_PROBLEM
                * ACKNOWLEDGE_SVC_PROBLEM
                * PROCESS_HOST_CHECK_RESULT
                * PROCESS_SERVICE_CHECK_RESULT
                * SCHEDULE_AND_PROPAGATE_HOST_DOWNTIME
                * SCHEDULE_AND_PROPAGATE_TRIGGERED_HOST_DOWNTIME
                * SCHEDULE_HOST_CHECK
                * SCHEDULE_HOST_DOWNTIME
                * SCHEDULE_SVC_CHECK
                * SCHEDULE_SVC_DOWNTIME
            query:  json of the parameters needed for each command. Be aware that most of the commands require different paramters

        Returns: Boolean: True if successful, False if not
        """
        return self.command_operation(command_type,query)

    def filter(self,filter_type,query):
        """
        Send a filter request to op5

        Parameters:
            filter_type: 
                Should be one of:
                    * count
                    * query
            query:
                The query string. Be aware of the correct usage of quotes.
                Example: '[hosts] name = "HOSTNAME"'

        Returns:
            json of the query result
        """
        return self.operation_querystring("/filter/"+filter_type,query)

    def report(self,query):
        return self.operation_querystring("/report/event",query)

    # define a method for bulk operations
    # This is needed as op5 gets unresponsive if too many operations take place at a time
    # therefore we should limit the amount of operations and cut bulks into slices
    def bulk_operation(self, api_method, object_list, slice_size):
        """
        Do an api_method as safe bulk operation.

        Parameters:
            api_method:     the method intended to run.
            object_list:    A list of dictionaries each containing the key:values of all arguments required for api_method
            slice_size:     The slice size defines how many operations should be executed before a persistence call is made

        This is actually only impemented on the delete() and create() methods
        """

        # we need to follow the index to know when a slice was filled
        for index, kwargs in enumerate(object_list):
            api_method(**kwargs)
            
            if index > 0 and index % slice_size == 0:
                self.commit_changes(force=True)

        self.commit_changes(force=True)
        

    def create(self,object_type,data_dict, *args, **kwargs):
        """
        Creates a new object. You should consolidate the op5 api documentation to know about requiered params for each object type.

        Parameters:
            object_type:
                * service
                * host
                * ...
            data_dict:
                dictionary with all needed parameters for the object which should be created

        Here is an example for a new service object:

            data_dict = {
                "check_command": "check_snmpif_status_v2",
                "check_command_args": "'snmp_community'!210!c",
                "check_interval": 2,
                "check_period": "24x7",
                "file_id": "etc/services.cfg",
                "host_name": "SWITCH1",
                "max_check_attempts": 3,
                "notification_interval": 0,
                "notification_options": [
                    "c", 
                    "r", 
                    "w"
                ],
                "notification_period": "13x5",
                "retry_interval": 2,
                "service_description": "Interface xy Status",
                "template": "default-service",
            }
            
            create("service", data_dict)

        """
        return self.operation("POST",object_type,data=data_dict)

    def read(self,object_type,name):
        """
        Do a GET operation on an op5 object

        Parameters:
            object_type:
                Defines the type of object to be called. For details see your api documentation. Examples:
                    * service
                    * host
                    * hostgroup
                    * timeperiod
                    * host_template
                    * ....
            name:
                The name of the object. For a service this should be "<hostname>;<service name>"
                Example:
                    "myhost.my.domain;ping"

        Returns:
            json of the queried object
        """
        return self.operation("GET",object_type,name)

    def update(self,object_type,name,data):
        return self.operation("PATCH",object_type,name,data)

    def delete(self,object_type,name,*args, **kwargs):
        return self.operation("DELETE",object_type,name)

    def overwrite(self,object_type,name,data):
        return self.operation("PUT",object_type,name,data)

    def get_changes(self):
        """
        Displays staged changes. You will have to call commit_changes() to make those persistent.
        """
        return self.operation("GET","change")

    def undo_changes(self):
        return self.operation("DELETE","change")

    def commit_changes(self, force=False):
        """
        Displays staged changes and commits them. This is required to make changes persistent at op5.
        """
        fname = sys._getframe().f_code.co_name

        staged_changes = self.get_changes()
        if len(staged_changes) > 0: #there are changes to commit
            print colored("This is a list of staged changes:", "red")
            print(json.dumps(staged_changes, indent=4))
            if force:
              print(colored("committing changes...", "white"))
              return self.operation("POST","change")
            elif query_yes_no("Shall I commit those changes?", default="no"):
                return self.operation("POST","change")
            else:
                print("Ok, maybe next time")
                return False
        else:
            print colored("%s(): Not attempting commit since nothing has been modified on the server" % fname, "red")
            return False

    def get_group_members(self,object_type,group_name):
        if object_type in ["hostgroup","contactgroup","servicegroup","usergroup"]:
            if self.read(object_type,group_name):
                if "members" in self.data:
                    return self.data["members"]
            else:
                return []
        else:
            fname = sys._getframe().f_code.co_name
            print colored("%s(): object_type '%s' is not valid" % (fname,object_type), "red")
            return False

    def sync(self,object_type,name,data_at_source):
        if self.read(object_type,name): #get the information currently on the OP5 server
            data_at_destination=self.data
            for key in data_at_source:
                if (key not in data_at_destination
                    or (type(data_at_destination[key]) is list and set(data_at_source[key]) != set(data_at_destination[key])) # if there is at least one diff, using set() diffs here since order is not important
                    or data_at_source[key] != data_at_destination[key]):
                    if self.debug:
                        print "Data at source:",data_at_source
                        print "Data at destination:",data_at_destination
                    print key,":",data_at_source[key],"did not match", key,":",data_at_destination.get(key,None),"! Making an update request."
                    return self.update(object_type,name,data_at_source) #send an update request
        else:
            return self.create(object_type,data_at_source)

    # Function to check that all required object properties are set
    def validate_object(self,request_type,object_type,data):
        # Sublists denote that either of the values need to be present, but not both
        required_properties = {}
        required_properties["command"]           = ["command_line", "command_name"];
        required_properties["contact"]           = ["alias", "contact_name"];
        required_properties["default"]           = [["name", object_type+"_name"]];
        required_properties["graph_template"]    = ["check"];
        required_properties["hostdependency"]    = ["dependent_host_name", "host_name"];
        required_properties["hostescalation"]    = ["first_notification", "host_name", "last_notification", "notification_interval"];
        required_properties["service"]           = [["host_name", "hostgroup_name"], "service_description"];
        required_properties["servicedependency"] = ["dependent_service", "service"];
        required_properties["user"]              = ["username", "password"];

        if object_type in required_properties:
            required_properties_list = required_properties[object_type]
        else:
            required_properties_list = required_properties["default"]

        validation_passed = True # "passed" by default

        # Loop through required properties, and break out of loop if validation fails
        # If requirement is a list, only one of the properties has to exist for the object to be valid
        for req_prop in required_properties_list:
            if isinstance(req_prop, list):
                if not any (sub_req_prop in data for sub_req_prop in req_prop):
                    validation_passed = False
                    break
            else:
                # Set validation_passed to false if required properties are not found
                if req_prop not in data:
                    validation_passed = False
                    break

        if not validation_passed:
            print colored("%s(%s): All required properties for a %s object not set in data! data: %s" % (request_type, object_type, object_type, str(data)), "red")
            return False

        return True

    def validate_request(self,request_type,object_type,name,data):
        if request_type not in ["GET","POST","PATCH","PUT","DELETE"]:
            print colored("%s(%s): Invalid request type! name:'%s' data: %s" % (request_type, object_type, name, str(data) ), "red")
            return False

        if object_type != "change":
            valid_object_types = ["host","hostgroup","service","servicegroup","contact","contactgroup","host_template","service_template",
                                  "contact_template","hostdependency","servicedependency","hostescalation","serviceescalation","user","usergroup",
                                  "combined_graph","graph_collection","graph_template","management_pack","timeperiod","command"]
            if object_type not in valid_object_types:
                print colored("%s(%s): Invalid object type! name:'%s' data: %s" % (request_type, object_type, name, str(data) ), "red")
                return False

            if request_type in ["POST","PATCH","PUT"] and not data:
                print colored("%s(%s): data not set! data: %s" % (request_type, object_type, str(data) ), "red")
                return False
            if request_type in ["PATCH","PUT","DELETE"] and name == "": #GET can have an empty name
                print colored("%s(%s): name not set! data: %s" % (request_type, object_type, str(data) ), "red")
                return False
            if request_type != "POST" and object_type == "service" and name != "" and name.count(";") == 0:
                print colored("%s(%s): Invalid service name! name:'%s' data: %s" % (request_type, object_type, name, str(data) ), "red")
                return False
            if request_type == "POST":
                # Return False if False, otherwise continue
                if not self.validate_object(request_type, object_type, data):
                    return False

        return True

    def command_operation(self, command_type, data, rdepth=0):
        """
        Submit an op5 command

        Parameters:
            command_type: Should be one of:
                * ACKNOWLEDGE_HOST_PROBLEM
                * ACKNOWLEDGE_SVC_PROBLEM
                * PROCESS_HOST_CHECK_RESULT
                * PROCESS_SERVICE_CHECK_RESULT
                * SCHEDULE_AND_PROPAGATE_HOST_DOWNTIME
                * SCHEDULE_AND_PROPAGATE_TRIGGERED_HOST_DOWNTIME
                * SCHEDULE_HOST_CHECK
                * SCHEDULE_HOST_DOWNTIME
                * SCHEDULE_SVC_CHECK
                * SCHEDULE_SVC_DOWNTIME
            query:  json of the parameters needed for each command. Be aware that most of the commands require different paramters

        Returns: Boolean: True if successful, False if not
        """
        url = self.api_url + "/command/" + command_type

        if self.debug or self.dryrun:
            text = "POST" + " " + url
            text += " Sent data: " + str(data)
            print text
        if self.dryrun:
            return False

        http_headers = {'content-type': 'application/json'}

        try:
            r = requests.post(url, auth=(self.api_username, self.api_password), data=json.dumps(data), headers=http_headers, timeout=10, verify=self.verify_certificates)
        except Exception as e:
            self.data = str(e)
            import pprint; pprint.pprint(e)
            return False

        if self.debug:
            print r.status_code
            print r.text
            print r.headers

        try:
            self.data = json.loads(r.text)
        except ValueError as e:
            self.data = r.text
            if r.status_code == 509:
              print colored("ERROR: OP5 internal sanity protections activated. Please wait for a while and try again..","red")
              return
            if r.headers["content-type"].find("text/html") != -1:
                raise e
        self.status_code = r.status_code

        if r.status_code != 200: #200 OK
            #e.g. 400 Bad request (e.g. required fields not set), 409 Conflict (e.g. something prevents it), 401 Unauthorized, 403 Forbidden, 404 Not Found, 405 Method Not Allowed
            print colored("POST(command/%s): got HTTP Status Code %d %s. Sent data: %s" % (command_type, r.status_code, r.reason, str(data)), "red")
            print colored("POST(command/%s): got HTTP Response: %s" % (command_type, r.text), "red")
            if self.logtofile:
                logger.error("POST(command/%s): got HTTP Status Code %d %s. Sent data: %s" % (command_type, r.status_code, r.reason, str(data)))
                logger.error("POST(command/%s): got HTTP Response: %s" % (command_type, r.text))
                logger.debug("POST(command/%s): HTTP Response headers were: %s" % (command_type, r.headers) )
            return False

        if not self.interactive: #in interactive mode, skip the status text for successful requests, so that the JSON output can easily be piped into another command
            print colored("POST(command/%s): Sent data: '%s'" % (command_type, str(data)), "green")
        if self.logtofile:
            logger.info("POST(command/%s): Sent data: '%s'" % (command_type, str(data)))
        return True

    def operation_querystring(self, api_type, query, rdepth=0):
        url = self.api_url + api_type
        if api_type.startswith("/filter"):
            params = {"format": "json", "query": query}

        if self.debug or self.dryrun:
            text = "GET" + " " + url
            text += " Query string: '" + str(query) + "'"
            print text
        if self.dryrun:
            return False

        http_headers = {'content-type': 'application/json'}

        try:
            r = requests.get(url, auth=(self.api_username, self.api_password), params=params, headers=http_headers, timeout=10, verify=self.verify_certificates)
        except Exception as e:
            self.data = str(e)
            import pprint; pprint.pprint(e)
            return False

        if self.debug:
            print r.status_code
            print json.dumps(r.json(), indent=4)
            print r.headers

        try:
            self.data = json.loads(r.text)
        except ValueError as e:
            self.data = r.text
            if r.status_code == 509:
              print colored("ERROR: OP5 internal sanity protections activated. Please wait for a while and try again..","red")
              return
            #GET can return HTTP 200 OK with "index mismatch", but in any other non-success scenario, we should be receiving JSON, and not HTML
            if r.text.find("index mismatch") != -1 or (r.status_code not in [200,201] and r.headers["content-type"].find("text/html") != -1):
                raise e
        self.status_code = r.status_code

        if r.status_code != 200: #200 OK
            #e.g. 400 Bad request (e.g. required fields not set), 409 Conflict (e.g. something prevents it), 401 Unauthorized, 403 Forbidden, 404 Not Found, 405 Method Not Allowed
            print colored("GET(%s): got HTTP Status Code %d %s. Query string: %s" % (api_type, r.status_code, r.reason, query), "red")
            print colored("GET(%s): got HTTP Response: %s" % (api_type, r.text), "red")
            if self.logtofile:
                logger.error("GET(%s): got HTTP Status Code %d %s. Query string: %s" % (api_type, r.status_code, r.reason, query))
                logger.error("GET(%s): got HTTP Response: %s" % (api_type, r.text))
                logger.debug("GET(%s): HTTP Response headers were: %s" % (api_type, r.headers) )
            return False

        if not self.interactive: #in interactive mode, skip the status text for successful requests, so that the JSON output can easily be piped into another command
            print colored("GET(%s): Query string: '%s'" % (api_type, query), "green")
        if self.logtofile:
            logger.info("GET(%s): Query string: '%s'" % (api_type, query))
        return r.json()

    #CRUD: create, read, update, delete [, and overwrite]
    #INPUTS:
    #object_type: string #e.g. "host","hostgroup","service"
    #name: string
    #data: dictionary
    #RETURNS:
    #boolean indicating success/failure of operation
    #the response JSON text is loaded into a JSON object and put into self.data
    #the http status code is put into self.status_code
    # TODO:
    # make delete safe, so it is possible to delete objects with '/'
    def operation(self,request_type,object_type,name="",data=None,rdepth=0):
        url = self.api_url + "/config/" + object_type

        if not self.validate_request(request_type,object_type,name,data):
            return False

        # a little extra code here to fix the service name when referring to a hostgroup in the URL
        if (request_type in ["PATCH","PUT","DELETE"] or (request_type == "GET" and name != "")) and object_type == "service" and self.debug:
            print "INFO: Checking if the given name is a hostgroup first."
            if self.read("hostgroup",name.split(";")[0]):
                name += "?parent_type=hostgroup"

        if request_type in ["GET","PATCH","PUT","DELETE"] and object_type != "change":
            url += "/" + quote(name.encode("UTF-8"))

        if self.debug:
            text = request_type + " " + url
            if data:
                text += " Sent data: " + str(data)
            print text
        if self.dryrun and request_type != "GET":
            print colored("DRYRUN: "+self.get_debug_text(request_type,object_type,name,data), "yellow")
            return False

        http_headers={'content-type': 'application/json'}

        try:
            r = getattr(requests,request_type.lower()) (url,auth=(self.api_username, self.api_password), data=json.dumps(data), headers=http_headers, timeout=600, verify=self.verify_certificates)
        except Exception as e:
            self.data = str(e)
            import pprint; pprint.pprint(e)
            return False

        if self.debug:
            print r.status_code
            print r.text
            print r.headers

        try:
            self.data = json.loads(r.text)
        except ValueError as e:
            self.data = r.text
            if r.status_code == 509:
              rdepth+=1
              if rdepth < self.max_retries:
                  print colored("ERROR: OP5 internal sanity protections activated. Waiting for a while before trying again..","red")
                  time.sleep(self.retry_wait)
                  return self.operation(request_type,object_type,name,data,rdepth)
              else:
                  raise RuntimeError("Bailing out after 3 retries on HTTP 509 OP5 Sanity Protection Error")
            #GET can return HTTP 200 OK with "index mismatch", but in any other non-success scenario, we should be receiving JSON, and not HTML
            if r.text.find("index mismatch") != -1 or (r.status_code not in [200,201] and r.headers["content-type"].find("text/html") != -1):
                raise e
        self.status_code = r.status_code

        # Do some extra logging in failure cases. #except the 500 Internal Errors
        if r.status_code != 200 and r.status_code != 201 and r.status_code != 500: #200 OK, 201 Created, 500 Internal Error
            #e.g. 400 Bad request (e.g. required fields not set), 409 Conflict (e.g. something prevents it), 401 Unauthorized, 403 Forbidden, 404 Not Found, 405 Method Not Allowed
            print colored("%s(%s): got HTTP Status Code %d %s. Name: '%s'. Sent data: %s" % (request_type, object_type, r.status_code, r.reason, name, str(data)), "red")
            print colored("%s(%s): got HTTP Response: %s" % (request_type, object_type, r.text), "red")
            if self.logtofile:
                logger.error("%s(%s): got HTTP Status Code %d %s. Name: '%s'. Sent data: %s" % (request_type, object_type, r.status_code, r.reason, name, str(data)) )
                logger.error("%s(%s): got HTTP Response: %s" % (request_type, object_type, r.text) )
                logger.debug("%s(%s): HTTP Response headers were: %s" % (request_type, object_type, r.headers) )
            return False
        elif r.status_code == 500: #500 Internal Error
            rdepth+=1
            if rdepth < self.max_retries:
                json_obj = json.loads(r.text)
                if json_obj['error'] == "Export failed" and json_obj['full_error']['type'] == "nothing to do":
                    return False
                time.sleep(self.retry_wait)
                return self.operation(request_type,object_type,name,data,rdepth)
            else:
                raise RuntimeError("Bailing out after 3 retries on HTTP 500 Internal Error")

        #success! #200 OK, 201 Created

        #debug/status text
        if not self.interactive: #in interactive mode, skip the status text for successful requests, so that the JSON output can easily be piped into another command
            print colored(self.get_debug_text(request_type,object_type,name,data), "green")
        #log (successful) changes
        if request_type != "GET" and self.logtofile:
            logger.info(self.get_debug_text(request_type,object_type,name,data))

        if request_type != "GET" and object_type != "change": #if it is not a "read" request or a "commit" request
            self.modified = True
        elif object_type == "change" and (request_type in ["POST","DELETE"] or (request_type == "GET" and len(self.data) == 0)):
            self.modified = False #reset the modified flag after a successful commit, or after understanding that there is nothing to commit
        return r.json()
