## Overview

Join the AMD AI DevMaster Hackathon sponsored by AMD (Advanced Micro Devices, Inc.). The goals of this hackathon are focused on cutting-edge AI application ideas and high-performance AMD GPU technologies. Select your preferred track! Explore the endless possibilities of AI applications, unlock the full computing potential of AMD GPU with the fully open-source AMD ROCm software stack. Let the powerful AMD Radeon GPUs be your ultimate engine to realize creative ideas and run models!

The hackathon includes three tracks covering core directions of innovative AI application development. Whether you are good at turning ideas into practical applications or optimizing underlying technologies, you can find your ideal stage here!

## Where to apply AMD Radeon GPU

See Radeon-hackathon-2026-07/README.md at main · AMD-DEV-CONTEST/Radeon-hackathon-2026-07 [URL 🔗](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md)

## Track 1: Development of Multimodal Content Creation Tools

Develop lightweight and high-performance AI multimodal content creation tools based on the computing power of AMD Radeon GPU and the ROCm open-source software stack. Participants may independently define creative styles and application scenarios, and build interesting applications leveraging GPU computing. For example, apply intelligent style transfer and secondary creation to images, short videos and other materials. Convert real scenes, daily footage and commercial content into audio-visual works with custom styles including animation, cyberpunk, retro texture, minimalist art and more.

This track focuses on four core directions: lightweight deployment, inference acceleration, style customization and image quality optimization. It aims to fully tap the multimodal computing advantages of AMD GPU, and deliver practical, efficient and personalized AI content generation solutions applicable to personal creation, new media operation, commercial visual design, short video production and various other industrial scenarios.

## Track 2: Development and Local Deployment of Private AI Agents

Adopt open-source AI Agent development kits to complete full-process local private deployment on AMD Radeon GPU and ROCm platform, and build highly adaptable and customizable dedicated AI Agents. Participants may define application scenarios freely to break the functional limitations of general AI tools and create agents with scenario-based service capabilities.

Available use cases include personal intelligent assistants, office automation assistants, industry-specific service agents, daily life management tools and more. This track


mainly assesses participants' capabilities to optimize Agent inference speed with AMD GPU computing power, improve the stability of local deployment and realize customized iterative functions. The goal is to build lightweight, highly available and private AI

intelligent service terminals.

## Track 3: Physical AI Challenge – Robotics Simulation and Application Design based on AMD Radeon GPU and ROCm

This track combines physics simulation technologies and Physical AI algorithms, leveraging the computing power of AMD Radeon GPU and ROCm open-source software stack to develop simulation systems and autonomous control solutions for robotic interaction scenarios. Participants may choose robot embodiments such as robotic arms, humanoid robots, wheeled robots, and quadruped robots, and complete Physical AI tasks such as motion planning, dynamic balance, object interaction, and

autonomous operation.

Supported application scenarios include precise grasping and placement of intelligent robotic arms, autonomous navigation and obstacle avoidance of mobile robots, dynamic gait control of quadruped robots, physical interaction control of multiple rigid bodies and other tasks without restrictions. All environment execution, model training and real-time inference must be completed on a single AMD Radeon GPU. Participants need to optimize the whole pipeline including physics simulation stepping, dynamics solving, and AI policy inference, to improve simulation performance, control responsiveness, and task stability.

This track focuses on four core areas: physics simulation design, the development of lightweight Physical AI models and algorithms, GPU computing scheduling, and end-to-end latency optimization. It aims to fully explore the capabilities of AMD Radeon GPU in parallel computing, real-time simulation and AI inference, while delivering lightweight, low-latency and deployable robotic Physical AI solutions. The outcomes can facilitate the application of physics simulation, robotic control, and embedded agents in

personal R&D, teaching and training, small intelligent devices, and other scenarios.

## Prize

For each track, you’ll get chance to win:

1st place: 5,000 USD

2nd place: 3,500 USD

3rd place: 1,500 USD


All prizes, eligibility requirements, scoring methodology, evaluation criteria, and payment terms are governed by this document of rules, terms, and conditions. Participants are responsible for reviewing this document prior to submission.

## How to Participate

- Registration: Register opens on July 10th 12:00 AM PDT, please register through AMD AI DevMaster Hackathon · Luma to be eligible to win prizes. [URL 🔗](https://luma.com/amd-4dhi)

- Eligibility: [URL 🔗](https://luma.com/amd-4dhi)

- Open to individuals or teams of up to three (3) members. Additional eligibility criteria apply as per rules, terms, and conditions in this document.

- Must be an AMD Developer Program member, and please join the program from here: [URL 🔗](https://www.amd.com/en/developer/ai-dev-program.html)

- Global developers: AMD Developer Program [URL 🔗](https://www.amd.com/en/developer/ai-dev-program.html)

- Only for developers in Mainland China: AMD Developer Program China [URL 🔗](https://developer.amd.com.cn/)

- Community & Support: Join the AMD Discord channel https://discord.gg/zt9caur5B3 for announcements, technical discussions, Q&A, and support throughout the competition. [URL 🔗](https://discord.gg/zt9caur5B3?utm_source=luma)

- Submission Process: please fork a sub repo of AMD-DEV-CONTEST/Radeon-hackathon-2026-07: Radeon hackathon on 2026-07 and create a pull request including your submission so that we can judge your great work. [URL 🔗](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)

## Hackathon Schedule

## Registration Opens

- Beijing/Singapore (UTC+8): July 10, 2026, 12:00 AM

- Europe (CEST): July 9, 2026, 6:00 PM

- US Pacific (PDT): July 9, 2026, 9:00 AM

## Submission Opens

- Beijing/Singapore (UTC+8): July 15, 2026, 12:00 AM

- Europe (CEST): July 14, 2026, 6:00 PM

- US Pacific (PDT): July 14, 2026, 9:00 AM

## Hackathon Ends / Final Submission Deadline

- Beijing/Singapore (UTC+8): August 6, 2026, 11:59 PM

- Europe (CEST): August 6, 2026, 5:59 PM

- US Pacific (PDT): August 6, 2026, 8:59 AM


## Rules

## Track 1: Development of Multimodal Content Creation Tools

Leverage the computing power of AMD Radeon GPU and the ROCm open-source software stack to develop a practical, lightweight and high-performance AI multimodal content creation tool. Your work shall support at least one core creation task as listed below:

- Image style transfer

- Image generation / image editing

- Text-to-image / Image-to-image

- Stylized processing for short video clips

- Image & video quality enhancement

- Secondary creation and batch processing of audio-visual content

- Text-to-video

- Image-to-video

- Etc.

Participants may independently define creative themes and application scenarios, such as new media content production, personal creation, commercial visual design, short video production and more.

To ensure unified competition standards, the required tech stack is defined as follows:

(1) Hardware & Platform Requirements

- Must run on AMD Radeon GPU from Radeon cloud

- Must adopt the ROCm software stack

- The final work shall be deployable and demonstrable on the designated AMD environment

- (2) Recommended Frameworks

- PyTorch + ROCm

- ComfyUI / Diffusers / Transformers (ensuring compatibility with AMD Radeon GPU)

- Auxiliary libraries: OpenCV / FFmpeg / Pillow, etc.

- Other eligible frameworks

- (3) Model Requirements

- Open-source models can be adopted for engineering modification and optimization

- LoRA, ControlNet, lightweight inference models and distilled models are permitted

- It is not allowed to rely solely on closed-source online APIs for core functions

- At least one key inference process must run locally on AMD Radeon GPU

The work shall be presented in at least one of the following demonstrable forms:

- Web UI

- Desktop Application

- Plugin tool (e.g., workflow plugin for creation)

- CLI tool + Demo workflow

- Other valid forms

## 1. Task Description

## 2. Specified Tech Stack

## (4) Deliverable Formats


## 3. Evaluation Criteria (Total: 100 Points)

- (1) Functional Completeness & Application Value (80 Points)

- Complete input-processing-output workflow: 40 points

- Innovative and interesting creation scenarios: 20 points

- Practical application and social value: 20 points

- (2) Operational Performance on AMD Radeon GPU (20 Points)

- Clear, stable and diverse output of the tool: 20 points

- 1. Project Profile Document (PDF)

- Project background

- Target users & application scenarios

- System architecture

- Model & algorithm introduction

- Adaptation description for AMD Radeon GPU / ROCm

- 2. Project Source Code

- Complete source code repository

- README file including environment configuration, startup guide and dependency list

- 3. Demo Video

- Recommended duration: 3–5 minutes

- Demonstrate the actual operation process

- The actual execution performance on an AMD Radeon GPU, from command line/GUI to the final result. (clarity, stability and diversity of outputs)

- 4. Supplementary Materials (Choose One)

- PPT / Poster (highlight creative scenarios, practical value of the tool)

## 4. Submission Requirements

## Track 2: Development & Local Deployment of Private AI Agents

Based on AMD Radeon GPU and the ROCm platform, combined with open-source AI Agent development frameworks, build a fully locally deployed, customizable AI Agent system with toolchain invocation capabilities. Your work shall target specific application scenarios, including but not limited to:

- Personal intelligent assistant

- Office automation assistant

- Industry-specific service Agent

- Local knowledge base Q&A assistant

- Schedule / Document / Email processing assistant

- Life management AI Agent

- Other customized scenarios

The work shall demonstrate the following capabilities:

- 1. Local deployment on AMD Radeon GPU

- 2. Execution of scenario-based tasks

- 3. Tool invocation & workflow orchestration

- 4. Operational stability and response performance in local runtime

## 1. Task Description

## 2. Specified Tech Stack


(1) Platform Requirements

- Must run on AMD Radeon GPU of Radeon cloud + ROCm software stack

- Core inference processes shall be executed locally on AMD Radeon GPU; remote APIs are not allowed for core functions

- It is not allowed to depend entirely on closed-source Agent platforms to implement core features

(2) Optional Frameworks & Applications

- vLLM / llama.cpp (adapted for AMD Radeon GPU)

- Transformers + PyTorch ROCm

- Optional Agent frameworks: Dify / LangChain / LlamaIndex / AutoGen / CrewAI / OpenWebUI, CherryStudio, etc, any you love but have to be neutral framework.

extra credits):

(3) Minimum Functional Requirements The work shall implement at least 2 of the following 5 capabilities (more capabilities will earn

- Local knowledge retrieval (RAG)

- Tool invocation

- Multi-step task planning

- Local multi-turn memory

- Clear permission control & privacy protection mechanism

## 3. Evaluation Criteria (Total: 120 Points)

(1) Functional Completeness of AI Agent (60 Points)

- Clear task positioning and creative application scenarios: 20 points

- Complete core capabilities including task decomposition, tool invocation, RAG and memory management: 20 points

- Smooth multi-turn interaction experience: 20 points

(2) Adaptation & Optimization for AMD Radeon GPU / ROCm (40 Points)

- Core inference running on AMD Radeon GPU: 20 points

- Targeted optimization for inference speed: 20 points

Optional bonus points (20 points):

- Core inference running Using Radeon cloud model API with quantization or distillation or other optimization methods.

- 4. Submission Requirements

- 1. Project Specification Document

- Application scenarios

- Agent architecture diagram

- Introduction to core capabilities

- Model introduction & local deployment plan

- Optimization description for inference speed on AMD Radeon GPU

- 2. Project Source Code

- Complete source code repository

- README file including environment configuration, startup guide and dependency list

3. Demo Video

- Recommended duration: 3–5 minutes

- Demonstrate the actual operation process

- The actual execution performance on an AMD Radeon GPU, from command line/GUI to the final result. (fluidity and functional completeness)

- 4. Supplementary Materials (Choose One)

- PPT / Poster


## Track 3: Physical AI Challenge – Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm

- 1. Task Description

Design and develop a complete robotic application pipeline based on the AMD Radeon GPU and ROCm platform. The robot embodiment is not restricted and may include, but is not limited to, robotic manipulators, humanoid robots, quadruped robots, mobile robots, or other robotic systems.

The proposed solution should demonstrate one or more of the following capabilities:

- Simulation Capability: The ability to construct and utilize physics-based simulation environments for robotic tasks.

- Robot Learning Capability: The ability to train intelligent robotic policies using learning-based approaches.

- Generalization & Robustness: The ability to maintain stable performance under diverse environments, perturbations, or unseen scenarios.

- Closed-loop Control: The ability to perform inference-driven perception–decision–control loops for robotic execution.

- GPU Optimization Capability: The ability to effectively leverage AMD Radeon GPUs and the ROCm software stack for acceleration and optimization.

- Multimodal Perception Fusion Capability: The ability to fuse information from multiple sensing modalities to enhance perception and support robot decision-making.

Application domains may include, but are not limited to:

- Manipulation: Generalizable robotic grasping and manipulation tasks using robotic arms.

- Whole-body Manipulation: Coordinated full-body tasks performed by humanoid robots.

- Mobile Navigation: Autonomous navigation and obstacle avoidance for mobile robots.

- Legged Locomotion & Manipulation: Dynamic locomotion and task execution for quadruped robots.

- Complex Physical Interaction: Interactions involving flexible objects, deformable objects, or other challenging physical phenomena.

- Multi-Agent Robotics: Collaborative perception, planning, and execution among multiple robots.

- Autonomous Driving: Physics-driven simulation, closed-loop vehicle control, and robust policy generalization for autonomous driving across diverse traffic scenarios.

(1) Platform Requirements

- Solutions must be based on the AMD Radeon GPU of Radeon cloud and ROCm software stack.

(2) Recommended Development Frameworks

- Solutions should be built upon open-source robotic simulation frameworks, such as Genesis or MuJoCo. The use of open-source robot learning frameworks, such as LeRobot, OpenVLA, is highly encouraged where applicable.

- Open-source model training frameworks should be used.

(3) Model Requirements

## 2. Specified Tech Stack


- Participants are required to use open-source models for Embodied AI, Physical AI, robotics, or related applications. Recommended models include Ultralytics YOLO models for visual perception and detection.

- (4) Data Requirements

- Public datasets and/or self-built datasets may be used. Recommended database options include OceanBase and Milvus where applicable.

- Participants are responsible for ensuring that all datasets comply with applicable legal, licensing, and ethical requirements.

## 3. Evaluation Criteria (Total: 100 Points)

- (1) Robot Capability Performance (30 Points)

- Evaluated based on the effectiveness of task execution and the overall task completion performance of the robotic system.

- (2) AMD Radeon GPU & ROCm Adoption (20 Points)

- Key stages of the pipeline, including training and/or inference, should be executed on AMD Radeon GPUs.

- (3) Innovation (20 Points)

- Evaluated based on the novelty and originality of the proposed solution and application design.

- (4) Application Value (20 Points)

- Evaluated based on the relevance of the proposed application to real-world industry needs and practical impact.

- Applications with higher real-world value will receive higher scores.

- (5) Upstream Open-Source Community Contributions (10 Points)

- Contributions made during the competition to upstream open-source projects, particularly those improving support for AMD platforms, will be evaluated and rewarded.

(1) Technical Report

The technical report should include, but is not limited to, the following:

- Definition and description of the target application

- Overall system architecture and solution design

- Description of the datasets used for training and/or evaluation

- Explanation of how AMD Radeon GPUs are utilized during training, inference, and other relevant stages

- Description of the innovations, key technical contributions, and important aspects of the project

- Description of the final deliverables and output forms of the project

- Any additional information that participants believe highlights the strengths or unique aspects of their work

- Introduction of team members and their respective contributions

- (2) Project Source Code

- Dedicated source code repositories

- A Docker image containing the complete source code and all required components for running the project would be preferable

- (3) Reproducibility Instruction README

- Participants must provide a detailed README document containing:

- Environment setup instructions

- Execution and usage instructions

## 4. Submission Requirements


- Dependency specifications

- Step-by-step reproduction procedures

- Following the provided instructions should allow evaluators to reproduce the submitted results.

(4) Demonstration Video (Recommended Length 3~5 minutes)

- The video should demonstrate the complete workflow of the project, including command-line and/or GUI operations, execution procedures, and results.

(5) Supplementary materials in other formats may be submitted to demonstrate the value of the proposed technical solution.

## Where to submit

When you are ready for the above submission, please read the readme.md of AMD-DEV-CONTEST/Radeon-hackathon-2026-07: Radeon hackathon on 2026-07 and follow it [URL 🔗](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)

to create a pull request including your submission so that we can judge your great work. [URL 🔗](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)

In the event of a tie between any eligible entries, the tie is broken based on the judging criteria described above. The decisions of the judges are final and binding. If we do not receive a sufficient number of entries meeting the entry requirements, we may, in our sole discretion, select fewer winners than the number of prizes described above.If you are a potential winner, we will notify you by sending a message to the e-mail address, the phone number, or mailing address (if any) provided at the time of entry within seven (7) days following completion of judging. If the notification sent is returned as undeliverable, or you are otherwise unreachable for any reason, we may award the applicable prize to a runner-up. If there is a dispute as to who is the potential winner, we will consider the potential winner to be the authorized account holder of the e-mail address used to enter the Contest. If you are a potential winner, we may require you to sign an Affidavit of Eligibility, Liability/Publicity Release, and/or a W-9 tax form or W-8 BEN tax form within ten (10) days of notification. You are advised to seek independent counsel regarding the tax implications of accepting a prize. If you do not complete the required forms as instructed and/or return the required forms within the time period listed on the winner notification message, we may disqualify you and select a runner-up as the potential winner. Participants who are under 18 years old should provide a parent/guardian-signed waiver to allow participation and entry in the contest on the front end and this should be done for all minors who submit an entry. If a minor wins, the parent or guardian should sign the AMD Declaration - publicity and liability release on behalf of the minor.

For the winners from China, the rewards will be converted to CNY at the exchange rate published by the Bank of China on the disbursement date.

If you are confirmed as a winner of this contest, the following rules apply:

- \- You may not exchange your prize for cash or any other merchandise or services.


- However, if for any reason an advertised prize is unavailable, we reserve the right to substitute a prize of equal or greater value.

- \- You may not designate someone else as the winner. If you are unable or unwilling to accept a prize, we may award it to a runner-up.

- \- You will be solely responsible for all applicable federal, state, and local taxes related to accepting the prize, if you choose to accept the prize. The final amount transferred to the winner will be exclusive of the applicable federal tax withholding.

- \- If a prize is awarded to a project submitted by a team, the prize money will be distributed evenly among the team members.

## Terms and Conditions

## Registration and Eligibility:

- \- Luma event registration and approval is mandatory for prize eligibility.

- \- To register, fill out the registration form on Luma. Registration is subject to verification and approval by AMD.

- \- Registration to AMD Developer Program is a pre-requisite for prize eligibility. You can register via below link:. [URL 🔗](https://www.amd.com/en/developer/ai-dev-program.html)

- [https://www.amd.com/en/developer/ai-dev-program.html, or](https://www.amd.com/en/developer/ai-dev-program.html)

- https://developer.amd.com.cn/ for China mainland developers only. [URL 🔗](https://developer.amd.com.cn/)

- \- The challenge is open to individuals and teams of up to three (3) members. [URL 🔗](https://developer.amd.com.cn/)

- \- All team members must register using their legal name and contact details, and provide the same team name.

- \- Participants must be 18 years or older or of the age of majority in their country as of registration start date.

- \- Participants under 18 must present a parent/guardian-signed waiver to allow participation and entry in the contest.

- \- All participants must:

- \- Have a valid Discord ID

- \- Have a valid GitHub ID

- \- For questions: email: ai_dev_contests@amd.com

## Not eligible:

- \- Individuals who are nationals of Belarus, Burma, Cuba, Iran, North Korea, Russia, Syria, Sudan, Venezuela, Crimea, Donetsk, Luhansk, or any country subject to U.S. export controls or sanctions, regardless of legal residency, are ineligible to participate. This includes individuals listed on the U.S. Department of Commerce’s Bureau of Industry and Security (BIS) Entity List or the U.S. Department of the Treasury’s Office of Foreign Assets Control (OFAC) Specially Designated Nationals (SDN) list, as well as those employed by or representing entities on these lists.


- \- Employees of the Sponsor, its affiliates, subsidiaries, and agents, along with their immediate family members (defined as parents, children, siblings, spouse, or domestic partner) and household members, are not eligible.

## Code of Conduct:

Entries may NOT contain ANY of the following content:

- \- Content that is sexually explicit, profane, or pornographic.

- \- Content that is unnecessarily violent or derogatory of any ethnic, racial, gender, sexual orientation, gender identity, religious, professional, or age group.

- \- Content that promotes illegal drugs, firearms/weapons (or the use of any of the foregoing) or a particular political agenda.

- \- Content that defames, misrepresents or contains disparaging remarks about any third-party, including individuals or organizations.

- \- Content that communicates messages or images inconsistent with the positive images and/or goodwill to which we wish to associate.

- \- Content that violates any federal, state, or local law.

- \- Harassment, discrimination, or inappropriate behavior will result in disqualification.

- \- AMD reserves the right to disqualify any participant or team at its sole discretion.

## For all Entries:

Any language or information included in a participant’s registration or submission is deemed to be part of the participant’s entry, and participant gives AMD, its designees, successors, assigns, and licensees a royalty-free, irrevocable, non-exclusive worldwide license to use, reproduce, modify, publish, create derivative works from, and display the entry and all elements embodied therein, along with the participant’s name and/or social media account handle(s), in any manner, in whole or in part, on a worldwide basis, and to incorporate it into other works, in any form, media or technology now known or later developed, including for advertising, promotional, marketing and other purposes, without further payment or consideration, notification or permission. All Entries become the property of AMD, and none will be returned. If requested, participant will sign any documentation required for Sponsor or its designees, successors, assignees, and licensees to make use of the non-exclusive rights participant is granting to AMD. Released Parties (as defined below) are not responsible for lost, late, stolen, incomplete, inaccurate, invalid, un-intelligible, garbled, delayed, or misdirected posts, all of which will be void.

## Release:

By participating, Participant agrees to release and hold harmless AMD, and each of its respective subsidiaries, affiliates, suppliers, distributors, advertising/promotion agencies, and each of their respective parent companies and each such company’s officers, directors, employees and agents (collectively, the “Released Parties”) from and


against any claim or cause of action, including, but not limited to, damage to or loss of property, arising out of participation in the Challenge or receipt or use or misuse of any prize.

## Privacy:

Participants acknowledge and understand that all personal information submitted as part of the challenge will be collected and processed by AMD for the purpose of managing the challenge in accordance with its Privacy Notice, Participant can read more about their rights, how AMD handles participants’ personal information, and how to contact AMD in its Privacy Notice.

## Publicity:

Except where prohibited by applicable law, participation in the developer challenge constitutes each winner’s consent to AMD’s use of the winner’s name, city, state, province or county, and country, likeness, photograph, statements made by the winner about the challenge, about AMD, and/or prize information for the challenge in any media without further payment or consideration, including, but not limited to, posting winner lists online. All submissions become the property of AMD and none will be returned.

## General Conditions:

Sponsor reserves the right to terminate, amend, suspend, or modify the challenge in whole or in part, at any time and without notice or obligation, if in AMD’s sole discretion, any factor interferes with its proper conduct as contemplated herein. Without limiting the generality of the foregoing, if, for any reason, the challenge is not capable of running as planned, including infection by computer virus, bugs, tampering, unauthorized intervention, fraud, technical failures, or any other causes beyond the control of AMD, which corrupt or affect the administration, security, fairness, integrity or proper conduct of the challenge, AMD reserves the right, in its sole discretion, to disqualify any individual or team who tampers with the entry process. Any attempt by any person to deliberately undermine the legitimate operation of the challenge may be a violation of criminal and civil law, and should such an attempt be made, AMD reserves the right to fully seek damages from any such person permitted by law. AMD’s failure to enforce any term of these rules shall not constitute a waiver of that provision or of any other provision of these rules. The invalidity or unenforceability of any provision of these rules shall not affect the validity or enforceability of any other provision. If any provision of the rules is determined to be invalid or otherwise unenforceable, then the rules shall be construed in accordance with the terms as if the invalid or unenforceable provision was not contained therein.


## Limitations of Liability:

The Released Parties are not responsible, to the extent permitted by law, for: (1) any incorrect or inaccurate information, whether caused by participant, printing errors, or omission or by any of the equipment or programming associated with or utilized in the challenge; (2) technical failures of any kind, including, but not limited to malfunctions, interruptions, or disconnections in phone lines or network hardware or software; (3) unauthorized human intervention in any part of the entry process or the challenge; (4) technical or human error which may occur in the administration of the challenge or the processing of entries; or (5) any injury or damage to person or property which may be caused, directly or indirectly, in whole or in part, from participation in the challenge or receipt or use or misuse of any prize. If for any reason an entry is confirmed to have been erroneously deleted, lost, or otherwise destroyed or corrupted, participant or the team’s sole remedy is another entry in the contest, provided that if it is not possible to submit another entry due to discontinuance of the challenge, or any part of it, for any reason, AMD, in its sole discretion, may elect to hold a random drawing from among all eligible entries or, as the case may be, from among eligible entries received up to the date of discontinuance for any or all of the prizes offered herein. No more than the stated amount of prizes will be awarded.

NOTHING IN THESE RULES SHALL DISCLAIM, LIMIT, OR EXCLUDE LIABILITY FOR ANY LIABILITY THAT MAY NOT BE DISCLAIMED, LIMITED, OR EXCLUDED PURSUANT TO APPLICABLE LAW.

## Disputes:

Except where prohibited, participants agree that: (1) any and all disputes, claims and causes of action arising out of or connected with this challenge or any prize awarded shall be resolved individually, without resort to any form of class action, and exclusively by the United States District Court for the Western District of Texas or the appropriate Texas State Court located in Travis County, Texas; (2) any and all claims, judgments and awards shall be limited to actual out-of-pocket costs incurred, including costs associated with entering this challenge, but in no event attorneys’ fees; and (3) under no circumstances will participant be permitted to obtain awards for, and participant hereby waives all rights to claim, indirect, punitive, incidental and consequential damages and any other damages, other than for actual out-of-pocket expenses, and any and all rights to have damages multiplied or otherwise increased.

## Winners List:

The Winners List will be available in English in AMD Discord channel, after the close of the contest. Inquiries for the winners list must be received within fourteen (14) days of the close of the contest. Inquiries received after this time will not be honored.


## For EU Residents Only:

THE ABOVE CHOICE OF LAW MAY NOT RESULT IN DEPRIVING THE PARTICIPANTS OF THE PROTECTION UNDER MANDATORY STATUTORY PROVISIONS THAT CANNOT BE WAIVED UNDER THE LAW WHICH WOULD HAVE BEEN APPLICABLE IN THE ABSENCE OF THIS CHOICE OF LAW. FOR PARTICIPANTS NOT RESIDING IN THE EUROPEAN UNION, any and all claims, judgments and awards shall be limited to actual out-of-pocket costs incurred, including costs associated with entering this Challenge, but in no event attorneys’ fees, and under no circumstances will Participant be permitted to obtain awards for, and Participant hereby waives all rights to claim, indirect, punitive, incidental, and consequential damages and any other damages, other than for actual out-of-pocket expenses, and any and all rights to have damages multiplied or otherwise increased. ANY DEMAND FOR OUT-OF-POCKET COMPENSATION MUST BE FILED WITHIN ONE (1) YEAR FROM THE END OF THE CHALLENGE PERIOD, OR IN ACCORDANCE WITH THE LAW OF LIMITATIONS AS APPLICABLE LOCALLY, OR THE CAUSE OF ACTION SHALL BE FOREVER BARRED. All issues and questions concerning the construction, validity, interpretation and enforceability of these Rules, or the rights and obligations of the Participant and AMD in connection with the Contest, shall be governed by, and construed in accordance with, the laws of the State of Texas without giving effect to any choice of law or conflict of law rules (whether of the State of Texas or any other jurisdiction), which would cause the application of the laws of any jurisdiction other than the State of Texas. Some jurisdictions do not allow for limitations of certain remedies or damages and so this provision may not apply to you.

THE ABOVE CHOICE OF LAW MAY NOT RESULT IN DEPRIVING THE PARTICIPANTS OF THE PROTECTION UNDER MANDATORY STATUTORY PROVISIONS THAT CANNOT BE WAIVED UNDER THE LAW WHICH WOULD HAVE BEEN APPLICABLE IN THE ABSENCE OF THIS CHOICE OF LAW. FOR PARTICIPANTS NOT RESIDING IN THE EUROPEAN UNION, any and all claims, judgments and awards shall be limited to actual out-of-pocket costs incurred, including costs associated with entering this Challenge, but in no event attorneys’ fees, and under no circumstances will Participant be permitted to obtain awards for, and Participant hereby waives all rights to claim, indirect, punitive, incidental, and consequential damages and any other damages, other than for actual out-of-pocket expenses, and any and all rights to have damages multiplied or otherwise increased. ANY DEMAND FOR OUT-OF-POCKET COMPENSATION MUST BE FILED WITHIN ONE (1) YEAR FROM THE END OF THE CHALLENGE PERIOD, OR IN ACCORDANCE WITH THE LAW OF LIMITATIONS AS APPLICABLE LOCALLY, OR THE CAUSE OF ACTION SHALL BE FOREVER BARRED. All issues and questions concerning the construction, validity, interpretation and enforceability of these Rules, or


the rights and obligations of the Participant and AMD in connection with the Contest, shall be governed by, and construed in accordance with, the laws of the State of Texas without giving effect to any choice of law or conflict of law rules (whether of the State of Texas or any other jurisdiction), which would cause the application of the laws of any jurisdiction other than the State of Texas. Some jurisdictions do not allow for limitations of certain remedies or damages and so this provision may not apply to you.

## For Germany Residents Only:

AMD will be liable for any culpable breach of essential contractual obligations. Essential contractual obligations are contractual obligations that need to be fulfilled to permit proper execution of these Rules and that may regularly be relied upon by the participant. AMD’s liability will otherwise be limited to gross negligence and willful misconduct. In the event of any liability on the part of AMD due to a slightly negligent breach of essential contractual obligations or slightly negligent misconduct on the part of simple vicarious agents, such as the Administrator, the AMD’s and the Administrator’s respective subsidiaries, affiliates, suppliers, distributors, advertising/promotion agencies, and prize suppliers, and each of their respective parent companies and each such company’s officers, directors, employees and agents, AMD’s liability will be limited to typically foreseeable damages. The above limitations of liability will not affect any mandatory statutory liability, in particular AMD’s liability in connection with the loss of life, bodily injury or illness.

## For UK Residents Only:

NOTWITHSTANDING THIS SECTION (LIMITATION OF LIABILITY), NOTHING IN THESE RULES SHALL BE CONSTRUED TO LIMIT OR EXCLUDE ANY LIABILITY OF THE AMD FOR FRAUD, DEATH, OR PERSONAL INJURY CAUSED BY AMD OR PARTICIPANTS’ NEGLIGENCE. No term herein is enforceable by any person who is not a party under the Contracts (Rights of Third Parties) Act 1999 or otherwise, excluding AMD.

TO THE EXTENT PERMITTED BY LAW, ANY CLAIMS OR DISPUTES RELATING TO THIS CHALLENGE, THE PRIZE OR THESE RULES MUST BE BROUGHT WITHIN ONE (1) YEAR OF THE TIME THE CAUSE OF ACTION OCCURRED.
