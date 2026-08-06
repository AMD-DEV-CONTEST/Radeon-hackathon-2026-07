import asyncio
from agent import run_agent

async def main():
    events = []
    async for ev in run_agent("Design an 8-bit synchronous up-counter with active-high synchronous reset and enable"):
        events.append(ev)
    print(f"Total events emitted: {len(events)}")
    print(f"Last event type: {events[-1]['type']}")
    msg = str(events[-1].get('message', events[-1])).encode('ascii', 'replace').decode('ascii')
    print(f"Final result message: {msg}")
    print(f"Lint Status: {events[-1].get('lint_status')}")
    print(f"Functional Status: {events[-1].get('functional_status')}")

if __name__ == "__main__":
    asyncio.run(main())
