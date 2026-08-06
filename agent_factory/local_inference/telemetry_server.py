from agent_factory.env import load_agentfactory_dotenv
from agent_factory.local_inference.node_server import create_app, main


load_agentfactory_dotenv()
app = create_app()


if __name__ == "__main__":
    main()
