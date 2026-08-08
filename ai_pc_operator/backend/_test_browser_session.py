import asyncio, json, sys, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, '.')
from httpx import ASGITransport, AsyncClient
from app.main import app, init_db, close_db
from app.security.pairing import PairingManager
from app.security.pairing_v2 import PairingManagerV2
from app.approvals.manager import ApprovalManager
from app.agent.router import AgentRouter
from app.tools.system_tools import SystemTools
from app.tools.file_tools import FileTools
from app.tools.browser_tools import BrowserTools
from app.tools.auth_tools import AuthTools
from app.tools.screen_tools import ScreenTools

async def run():
    await init_db()
    import app.main as main_mod
    main_mod.pairing_manager = PairingManager()
    main_mod.pairing_manager_v2 = PairingManagerV2()
    main_mod.approval_manager = ApprovalManager()
    main_mod.agent_router = AgentRouter(
        approval_manager=main_mod.approval_manager,
        system_tools=SystemTools(),
        file_tools=FileTools(),
        browser_tools=BrowserTools(),
        auth_tools=AuthTools(),
        screen_tools=ScreenTools(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        code_resp = await client.get('/pair/code')
        code = code_resp.json().get('code', '')

        pair_resp = await client.post('/pair', json={'code': code, 'device_name': 'Test Phone'})
        pair_data = pair_resp.json()
        device_id = pair_data.get('device_id', '')
        token = pair_data.get('token', '')
        print('DEVICE_ID:', device_id)

        cmd_resp = await client.post('/command',
            json={'text': 'browser_session', 'device_id': device_id},
            headers={'Authorization': 'Bearer ' + token}
        )
        print('STATUS:', cmd_resp.status_code)
        result = cmd_resp.json()
        print('intent:', result.get('intent'))
        print('risk:', result.get('risk'))
        print('status:', result.get('status'))
        print('requires_approval:', result.get('requires_approval'))
        if 'execution_graph' in result:
            graph = result['execution_graph']
            if isinstance(graph, list):
                print('graph nodes:', len(graph))
                for n in graph:
                    nid = n.get('id', '?')
                    ntype = n.get('type', '?')
                    nrisk = n.get('risk', '?')
                    print('  - ' + nid + ': ' + ntype + ' (risk=' + str(nrisk) + ')')
        if 'plan' in result:
            plan = result['plan']
            if isinstance(plan, dict):
                print('plan steps:', len(plan.get('steps', [])))
                for s in plan.get('steps', []):
                    print('  -', s.get('tool', s.get('action', '?')))
        print('result:', str(result.get('result', ''))[:300])

    await close_db()

asyncio.run(run())
