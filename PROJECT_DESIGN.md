here is the project outline

we are going to build a diary app. the use case will be the following:
the user will open the browser at anytime of the day. the default page will load, and started listening. there is no action the user needed to do. the default page shows a dotted face. if the user didn't speak for a reasonable time, e.g. 5 s, the agent will start asking the user, e.g. how's the day? or normal greeting.

the user will talk to the agent. all the info will be summarized to a graph for the day. the user can also change the target date on the right side of the screen though a scrolling date picker. the yesterday and day before yesterday, tomorrow, and the day after tomorrow will be showed as quick action. the tomorrow and day after tomorrow has different color. it can be used to set "plan" or todos.

the agent will talk to the user like an interviewer or friend.

the agent may prompt the user to speak more details. e.g. when the user didn't provide enough detail, the agent will ask the user for more info.

the agent will also check the "todo" node. the user may say "I plan to do xxxx tomorrow". if the user didn't talk about that on that day, the agent may ask for clearification.

you may design the graph data structure and RBAC

the graph infrastructure is at:
/home/pdfexe/neo4j/bionic-graph/AGENTS.md


you may take full advantage of the rocm gpu for heavy-lifting LLM inferencing. you may build MCP or any other protocol around the agent so it can access the graph database. You have to think about what permission is necessary for the agent to perform. 
