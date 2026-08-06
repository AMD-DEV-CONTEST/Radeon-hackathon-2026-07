"""Load test data into Neo4j."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.neo4j_client import Neo4jClient
from database.schema_loader import format_schema_for_llm, get_schema


def main():
    # Check connectivity
    print("Checking Neo4j connectivity...")
    if not Neo4jClient.health_check():
        print("ERROR: Cannot connect to Neo4j. Is docker-compose up?")
        sys.exit(1)
    print("Connected!")

    # Load test data from Cypher file
    data_file = Path(__file__).parent / "test_data.cypher"
    if not data_file.exists():
        print(f"ERROR: Test data file not found: {data_file}")
        sys.exit(1)

    cypher_content = data_file.read_text()

    # Remove comments and blank lines, then execute as a single transaction
    # to preserve variable references between CREATE statements
    lines = [l for l in cypher_content.split("\n") if l.strip() and not l.strip().startswith("//")]
    clean_script = "\n".join(lines)

    print("Loading test data...")
    driver = Neo4jClient.get_driver()

    with driver.session(database="neo4j") as session:
        session.run(clean_script)

    print("Test data loaded!")

    # Display schema
    print("\n--- Graph Schema ---")
    schema = get_schema()
    print(format_schema_for_llm(schema))

    # Quick stats
    nodes = Neo4jClient.execute("MATCH (n) RETURN count(n) AS count")
    rels = Neo4jClient.execute("MATCH ()-[r]->() RETURN count(r) AS count")
    print(f"Total nodes: {nodes[0]['count']}, Total relationships: {rels[0]['count']}")


if __name__ == "__main__":
    main()
