op5lib
======
A Python library for OP5's REST API.

Best Practices
--------------

- Whenever possible use hostgroups to encapsulate and categorize service checks (and NOT separate service objects for every new host), and host templates to automatically set a default host check command with the right arguments for all hosts that fit a particular pattern.

Pitfalls
--------

- Do NOT make changes towards the API as part of a node coming up, or at the least, do not save the changes (aka export the database) at the end of the run. This could potentially result in a high number of nodes exporting the database one after another causing (currently) about 6 seconds of downtime for OP5 software (e.g. the OP5 GUI, and the REST API, not Nagios) for every single such call. (along with the risk for conflicts, causing downtime for an indefinite amount of time. (i.e. until the operator manually intervenes and fixes the issue)

- Do NOT ever have multiple API sessions from the same user running at the same time!

- If after making sure of that, you still have problems, do NOT ever have multiple API sessions (from whatever user) running at the same time! This is the only way to make sure that everything would run smoothly.

These last two issues are because of the following bugs among potential others.

https://jira.op5.com/browse/MON-7477 (fixed in op5 Monitor 7.1.0)

https://jira.op5.com/browse/MON-7500 (fixed in op5 Monitor 7.1.8)

Contributing
------------
Pull requests, bug reports, and feature requests are extremely welcome.

