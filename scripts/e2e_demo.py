"""Full e2e demo: NL → DSL → backtest → paper trade → risk report.

This script demonstrates the complete pipeline including paper trading.
Safe for demo: defaults to DRY_RUN mode.

Usage:
    # DRY_RUN mode (no Testnet needed)
    python scripts/e2e_demo.py

    # Real Testnet mode (requires API keys)
    DRY_RUN=false python scripts/e2e_demo.py
"""
import sys, time, re, copy, ast, os, json
sys.path.insert(0, '/workspace/persistent/radeon-repo/track2-agentic-ai')
import yaml, httpx
from src.dsl.canonicalizer import canonicalize_dsl
from src.dsl.validator import validate_dsl
from src.dsl.transpiler import transpile_to_freqtrade
from src.dsl.transpiler_backtrader import transpile_to_backtrader

VLLM = 'http://localhost:8000/v1'
MODEL = 'models/qwen-trader-merged'
API = 'http://localhost:8080'

SYSTEM = (
    "You are an expert crypto trading strategist. "
    "Convert the user's natural language trading idea into a YAML strategy DSL. "
    "Output ONLY valid YAML.\n"
    "Rules: stop_loss MUST be negative in risk:. period MUST be integer. "
    "Only long/short in entry/exit. indicators MUST be non-empty list."
)

PROMPTS = [
    ('BTC 15分钟EMA20/EMA50金叉策略，回测+模拟交易，止损2%', 'BTC/USDT'),
    ('BTC放量突破前高，使用EMA20/EMA50，止损3%，回测并分析风险', 'BTC/USDT'),
]


def safe(val, default=0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def call_llm(prompt):
    with httpx.Client(timeout=120) as c:
        r = c.post(f'{VLLM}/chat/completions', json={
            'model': MODEL,
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}],
            'temperature': 0.2, 'max_tokens': 2048,
        })
        return r.json()['choices'][0]['message']['content']


def extract_yaml(text):
    for pattern in [r'```(?:ya?ml)?\s*\n(.*?)\n```', r'(^|\n)(strategy:\s*\n.*)']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                p = yaml.safe_load(m.group(1) if '```' in pattern else m.group(2))
                if isinstance(p, dict) and 'strategy' in p:
                    return p
            except yaml.YAMLError:
                pass
    try:
        p = yaml.safe_load(text)
        if isinstance(p, dict) and 'strategy' in p:
            return p
    except yaml.YAMLError:
        pass
    return None


def run_backtest(dsl):
    with httpx.Client(timeout=120) as c:
        r = c.post(f'{API}/api/backtest', json={'strategy': dsl, 'days': 180, 'initial_balance': 10000})
        return r.json()


def paper_trade(action, pair, amount=None):
    with httpx.Client(timeout=30) as c:
        r = c.post(f'{API}/api/paper-trade/execute', json={'action': action, 'pair': pair, 'amount': amount})
        return r.json()


def get_market(pair):
    try:
        with httpx.Client(timeout=10) as c:
            r = c.get(f'{API}/api/market/summary', params={'pair': pair})
            return r.json()
    except Exception:
        return {'last_price': 65000, 'change_pct': 0, 'volume_24h': 0, 'pair': pair}


def main():
    dry_run = os.environ.get('DRY_RUN', 'true').lower() not in ('false', '0', 'no')
    mode = 'DRY_RUN' if dry_run else 'TESTNET'

    print('=' * 70)
    print(f'  Full E2E Demo — NL → DSL → Backtest → Paper Trade → Report')
    print(f'  Mode: {mode} | GPU: AMD MI210 | Model: {MODEL}')
    print('=' * 70)
    print()

    nl, pair = PROMPTS[0]
    print(f'[1] INPUT: {nl}')
    print()

    # Step 1: LLM generates DSL
    t0 = time.time()
    raw = call_llm(nl)
    llm_time = time.time() - t0
    print(f'[2] LLM GENERATION ({llm_time:.1f}s on AMD GPU)')
    print(f'    Raw output (first 200 chars): {raw[:200]}')
    print()

    # Step 2: Extract + Canonicalize
    dsl = extract_yaml(raw)
    if not dsl:
        print('    EXTRACT FAILED — retrying with simpler prompt...')
        raw = call_llm('Create a simple EMA crossover strategy for BTC/USDT. EMA 20 and 50. Stop loss 3%. Output ONLY valid YAML.')
        dsl = extract_yaml(raw)
    if not dsl:
        print('    FATAL: Could not extract DSL')
        sys.exit(1)

    canon = copy.deepcopy(dsl)
    canon, repairs, errors = canonicalize_dsl(canon)
    strat_name = canon.get('strategy', {}).get('name', 'Unknown')
    print(f'[3] DSL CANONICALIZATION')
    print(f'    Strategy: {strat_name}')
    print(f'    Repairs: {len(repairs)}')
    for r in repairs[:3]:
        print(f'      {r.field}: {r.raw} -> {r.normalized} ({r.repair_type})')
    print()

    # Step 3: Validate + Transpile
    valid, verrors = validate_dsl(canon)
    ft_ok = bt_ok = False
    if valid:
        try: ast.parse(transpile_to_freqtrade(canon)); ft_ok = True
        except: pass
        try: ast.parse(transpile_to_backtrader(canon)); bt_ok = True
        except: pass
    print(f'[4] VALIDATION')
    print(f'    Schema: {"PASS" if valid else "FAIL"}')
    print(f'    Freqtrade: {"OK" if ft_ok else "FAIL"}')
    print(f'    Backtrader: {"OK" if bt_ok else "FAIL"}')
    print()

    if not valid:
        print('    SKIP: Invalid DSL — not proceeding to backtest')
        sys.exit(1)

    # Step 4: Market data
    market = get_market(pair)
    price = safe(market.get('last_price', 0))
    print(f'[5] MARKET DATA ({pair})')
    print(f'    Price: ${price:,.2f}')
    print(f'    24h change: {safe(market.get("change_pct")):+.1f}%')
    print(f'    24h volume: {safe(market.get("volume_24h")):,.0f}')
    print()

    # Step 5: Backtest
    t0 = time.time()
    bt = run_backtest(canon)
    bt_time = time.time() - t0
    m = bt.get('metrics', {})
    bt_error = bt.get('error', '')
    bt_valid = bt.get('is_valid', True)

    print(f'[6] BACKTEST ({bt_time:.1f}s, 180 days)')
    print(f'    Status: {"INVALID" if not bt_valid else "VALID"}')
    if not bt_valid:
        print(f'    Reason: {bt_error}')
    print(f'    Strategy: {bt.get("strategy_name")}')
    print(f'    Trades: {m.get("total_trades", 0)}')
    print(f'    Win rate: {safe(m.get("win_rate")):.1%}')
    print(f'    Total return: {safe(m.get("total_return")):.2%}')
    print(f'    B&H return: {safe(m.get("benchmark_return")):.2%}')
    print(f'    Alpha: {safe(m.get("alpha")):+.2%}')
    print(f'    Max drawdown: {safe(m.get("max_drawdown")):.2%}')
    print(f'    Sharpe: {safe(m.get("sharpe_ratio")):.2f}')
    print(f'    Final balance: ${safe(m.get("final_balance")):,.2f}')
    print(f'    Win/Loss: {m.get("win_trades", 0)}/{m.get("loss_trades", 0)}')
    print()

    # Step 6: Paper trading
    print(f'[7] PAPER TRADING ({mode})')
    trade_amount = 0.001  # 0.001 BTC ≈ $65 for demo

    if not bt_valid:
        print(f'    SKIP: Backtest INVALID — paper trade rejected')
        print(f'    Reason: {bt_error}')
        print()
        print(f'[8] RISK ASSESSMENT')
        print(f'    [REJECT] Backtest sanity check failed')
        print(f'    Reason: {bt_error}')
        print(f'    VERDICT: REJECT — strategy rejected, no paper trade executed')
        print()
        print('=' * 70)
        print(f'  DEMO COMPLETE')
        print(f'  LLM: {llm_time:.1f}s | Backtest: {bt_time:.1f}s | Mode: {mode}')
        print(f'  Strategy: {strat_name} | Verdict: REJECT (INVALID_BACKTEST)')
        print('=' * 70)
        return

    # Check market status
    pt_status = paper_trade('status', pair)
    print(f'    Market status: {pt_status.get("details", {}).get("last_price", 0):,.2f}')
    print(f'    Current position: {pt_status.get("details", {}).get("position", 0)}')

    # Execute buy
    pt_buy = paper_trade('buy', pair, trade_amount)
    print(f'    BUY {trade_amount} {pair}:')
    print(f'      Success: {pt_buy.get("success")}')
    if pt_buy.get('success'):
        d = pt_buy.get('details', {})
        print(f'      Order ID: {d.get("order_id")}')
        print(f'      Fill price: ${safe(d.get("fill_price")):,.2f}')
        print(f'      Value: ${safe(d.get("value_usd")):,.2f}')
        print(f'      Position: {d.get("position")}')
    else:
        print(f'      Error: {pt_buy.get("error")}')

    # Check balance
    pt_bal = paper_trade('balance', pair)
    if pt_bal.get('success'):
        total = pt_bal.get('details', {}).get('total', {})
        print(f'    Balance: {json.dumps(total)}')
    print()

    # Step 7: Risk Assessment
    sharpe = safe(m.get('sharpe_ratio'))
    dd = safe(m.get('max_drawdown'))
    alpha = safe(m.get('alpha'))
    consec = m.get('max_consecutive_losses', 0)
    win_rate = safe(m.get('win_rate'))

    print(f'[8] RISK ASSESSMENT')
    risks = []
    if sharpe > 1.0:
        print(f'    [OK] Sharpe > 1.0: Acceptable ({sharpe:.2f})')
    else:
        print(f'    [WARN] Sharpe < 1.0: Low risk-adjusted return ({sharpe:.2f})')
        risks.append('Low Sharpe')

    if dd > -0.20:
        print(f'    [OK] Max DD < 20%: Controlled ({dd:.2%})')
    else:
        print(f'    [WARN] Max DD > 20%: High risk ({dd:.2%})')
        risks.append('High drawdown')

    if alpha > 0:
        print(f'    [OK] Alpha > 0: Beats B&H ({alpha:+.2%})')
    else:
        print(f'    [WARN] Alpha < 0: Underperforms B&H ({alpha:+.2%})')
        risks.append('Negative alpha')

    if consec > 5:
        print(f'    [WARN] Consecutive losses > 5: Sustainability risk ({consec})')
        risks.append('Consecutive losses')

    if win_rate < 0.30:
        print(f'    [WARN] Win rate < 30%: Low hit rate ({win_rate:.1%})')
        risks.append('Low win rate')

    verdict = 'APPROVE' if (sharpe > 0 and alpha > 0 and dd > -0.30 and len(risks) <= 1) else 'MODIFY'
    if len(risks) >= 3:
        verdict = 'REJECT'

    print()
    print(f'    VERDICT: {verdict}')
    print(f'    Paper trade mode: {mode}')
    print(f'    Position: {trade_amount} {pair.split("/")[0]} ({mode} only, not real funds)')
    print()

    # Summary
    print('=' * 70)
    print(f'  DEMO COMPLETE')
    print(f'  LLM: {llm_time:.1f}s | Backtest: {bt_time:.1f}s | Mode: {mode}')
    print(f'  Strategy: {strat_name} | Verdict: {verdict}')
    print(f'  Return: {safe(m.get("total_return")):.2%} | Sharpe: {sharpe:.2f} | DD: {dd:.2%}')
    print(f'  Paper position: {trade_amount} BTC ({mode})')
    print('=' * 70)


if __name__ == '__main__':
    main()
