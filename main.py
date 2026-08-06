import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process
from langchain_google_genai import ChatGoogleGenerativeAI

# Robustly load environment variables from .env
load_dotenv()

# Manual fallback in case dotenv path is resolved differently
if not os.environ.get("GEMINI_API_KEY") and os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                os.environ["GEMINI_API_KEY"] = line.split("=")[1].strip()

# Initialize Google Gemini model (Zero local storage, using the active stable model)
llm = ChatGoogleGenerativeAI(
    model="gemini-flash-latest",
    temperature=0,
    google_api_key=os.environ.get("GEMINI_API_KEY")
)

def read_contract(file_path):
    with open(file_path, 'r') as file:
        return file.read()

# Load the target contract
contract_code = read_contract('sample_contract.sol')

# 1. Define the Agents
auditor = Agent(
    role='Senior Smart Contract Auditor',
    goal='Identify security vulnerabilities in Solidity smart contracts',
    backstory='You are a Web3 security researcher specializing in finding critical smart contract vulnerabilities like reentrancy and access control bugs.',
    verbose=True,
    allow_delegation=False,
    llm=llm
)

reporter = Agent(
    role='Technical Security Writer',
    goal='Create structured, actionable markdown reports from audit findings',
    backstory='You translate complex security vulnerabilities into clear, professional documentation.',
    verbose=True,
    allow_delegation=False,
    llm=llm
)

# 2. Define the Tasks
audit_task = Task(
    description=f'Analyze the following Solidity code and list vulnerabilities, explaining how they can be exploited:\n\n{contract_code}',
    expected_output='A detailed list of vulnerabilities found in the contract.',
    agent=auditor
)

report_task = Task(
    description='Take the vulnerabilities found by the auditor and format them into a professional Markdown security report with Executive Summary, Findings, and Fixes.',
    expected_output='A complete Markdown document outlining the security audit results.',
    agent=reporter
)

# 3. Form the Crew and Execute
security_crew = Crew(
    agents=[auditor, reporter],
    tasks=[audit_task, report_task],
    process=Process.sequential
)

if __name__ == "__main__":
    print("Starting AI Agent Audit Pipeline...")
    result = security_crew.kickoff()
    
    # Save the output
    with open("audit_report.md", "w", encoding="utf-8") as f:
        f.write(result)
    
    print("\nAudit Complete! Check audit_report.md")
