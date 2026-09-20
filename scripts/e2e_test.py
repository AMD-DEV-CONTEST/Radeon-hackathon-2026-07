"""End-to-end test: NL → vLLM → DSL → canonicalize → validate → backtest → risk report.

This script demonstrates the complete pipeline that Dify would orchestrate.
Run on the GPU instance to verify the full chain works.
"""
import sys, json, time, re, copy, ast
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
    "Convert the user's natural language trading idea into a YAML strategy DSL specification. "
    "Output ONLY valid YAML.\n"
    "strategy:\n"
    "  name: StrategyName\n"
    "  market: {exchange: binance, pair: BTC/USDT, timeframe: 1h}\n"
    "  indicators: [{name: ema_fast, type: EMA, params: {period: 20, field: close}}]\n"
    "  entry: {long: 'ema_fast > ema_slow', short: null}\n"
    "  exit: {long: 'ema_fast < ema_slow', short: null}\n"
    "  risk: {stop_loss: -0.03, max_open_trades: 3, stake_amount: 0.1}\n"
    "Rules: stop_loss MUST be negative number in risk:. "
    "period MUST be integer. Only long/short in entry/exit."
)

NL_PROMPT = 'BTC放量突破前高，使用EMA20/EMA50，止损3%，帮我回测并分析风险'


def extract_yaml(text):
    m = re.search(r'```(?:ya?ml)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            p = yaml.safe_load(m.group(1))
            if isinstance(p, dict) and 'strategy' in p:
                return p
        except yaml.YAMLError:
            pass
    sm = re.search(r'(^|\n)(strategy:\s*\n.*)', text, re.DOTALL)
    if sm:
        try:
            p = yaml.safe_load(sm.group(2))
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


def main():
    print(f'INPUT: {NL_PROMPT}')
    print()

    # Step 1: LLM generates DSL
    t0 = time.time()
    with httpx.Client(timeout=120) as c:
        r = c.post(f'{VLLM}/chat/completions', json={
            'model': MODEL,
            'messages': [
                {'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': NL_PROMPT},
            ],
            'temperature': 0.2,
            'max_tokens': 2048,
        })
        raw = r.json()['choices'][0]['message']['content']
    llm_time = time.time() - t0
    print(f'LLM TIME: {llm_time:.1f}s')
    print(f'RAW DSL:')
    print(raw[:500])
    print()

    # Step 2: Extract YAML
    dsl = extract_yaml(raw)
    if not dsl or 'strategy' not in dsl:
        # Retry with shorter prompt
        print('EXTRACT FAILED — retrying with simpler prompt...')
        with httpx.Client(timeout=120) as c:
            r = c.post(f'{VLLM}/chat/completions', json={
                'model': MODEL,
                'messages': [
                    {'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': 'Create a simple EMA crossover strategy for BTC/USDT. EMA 20 and 50. Stop loss 3%. Output ONLY valid YAML.'},
                ],
                'temperature': 0.1,
                'max_tokens': 2048,
            })
            raw = r.json()['choices'][0]['message']['content']
        print(f'RETRY RAW[:300]: {raw[:300]}')
        dsl = extract_yaml(raw)
    if not dsl or 'strategy' not in dsl:
        print('EXTRACT FAILED (after retry)')
        sys.exit(1)
    strat_name = dsl.get('strategy', {}).get('name', 'Unknown')
    print(f'STRATEGY: {strat_name}')
    print()

    # Step 3: Canonicalize
    canon = copy.deepcopy(dsl)
    canon, repairs, errors = canonicalize_dsl(canon)
    print(f'CANONICALIZER: {len(repairs)} repairs, {len(errors)} errors')
    for rp in repairs[:5]:
        print(f'  {rp.field}: {rp.raw} -> {rp.normalized} ({rp.repair_type})')
    print()

    # Step 4: Validate
    valid, verrors = validate_dsl(canon)
    print(f'SCHEMA VALID: {valid}')
    if verrors:
        print(f'ERRORS: {verrors[:2]}')
    print()

    # Step 5: Transpile
    ft_ok = bt_ok = False
    try:
        ast.parse(transpile_to_freqtrade(canon))
        ft_ok = True
    except Exception as e:
        print(f'FT ERR: {e}')
    try:
        ast.parse(transpile_to_backtrader(canon))
        bt_ok = True
    except Exception as e:
        print(f'BT ERR: {e}')
    print(f'TRANSPILE: Freqtrade={ft_ok}, Backtrader={bt_ok}')
    print()

    # Step 6: Backtest
    if valid:
        t0 = time.time()
        with httpx.Client(timeout=120) as c:
            r = c.post(f'{API}/api/backtest', json={
                'strategy': canon,
                'days': 180,
                'initial_balance': 10000,
            })
            bt = r.json()
        bt_time = time.time() - t0
        print(f'BACKTEST TIME: {bt_time:.1f}s')
        print(f'SUCCESS: {bt.get("success")}')
        m = bt.get('metrics', {})
        print()
        print(f'=== BACKTEST RESULTS ===')

        def safe_fmt(val, fmt, default=0):
            try:
                return fmt.format(float(val))
            except (TypeError, ValueError):
                return fmt.format(float(default))

        print(f'  Strategy:     {bt.get("strategy_name", "?")}')
        print(f'  Total trades: {m.get("total_trades", 0)}')
        print(f'  Win rate:     {safe_fmt(m.get("win_rate"), "{:.1%}")}')
        print(f'  Total return: {safe_fmt(m.get("total_return"), "{:.2%}")}')
        print(f'  B&H return:  {safe_fmt(m.get("benchmark_return"), "{:.2%}")}')
        print(f'  Alpha:        {safe_fmt(m.get("alpha"), "{:+.2%}")}')
        print(f'  Max drawdown: {safe_fmt(m.get("max_drawdown"), "{:.2%}")}')
        print(f'  Sharpe:       {safe_fmt(m.get("sharpe_ratio"), "{:.2f}")}')
        print(f'  Sortino:      {safe_fmt(m.get("sortino_ratio"), "{:.2f}")}')
        print(f'  Calmar:       {safe_fmt(m.get("calmar_ratio"), "{:.2f}")}')
        print(f'  Final bal:    ${safe_fmt(m.get("final_balance"), "{:,.2f}")}')
        print(f'  Win/Loss:     {m.get("win_trades", 0)}/{m.get("loss_trades", 0)}')
        print()

        print(f'=== RISK ASSESSMENT ===')
        sharpe = float(m.get('sharpe_ratio', 0) or 0)
        dd = float(m.get('max_drawdown', 0) or 0)
        alpha = float(m.get('alpha', 0) or 0)
        consec = m.get('max_consecutive_losses', 0)

        if sharpe > 1.0:
            print(f'  [OK] Sharpe > 1.0: Acceptable risk-adjusted return ({sharpe:.2f})')
        else:
            print(f'  [WARN] Sharpe < 1.0: Low risk-adjusted return ({sharpe:.2f})')

        if dd > -0.20:
            print(f'  [OK] Max DD < 20%: Controlled drawdown ({dd:.2%})')
        else:
            print(f'  [WARN] Max DD > 20%: High drawdown risk ({dd:.2%})')

        if alpha > 0:
            print(f'  [OK] Alpha > 0: Strategy beats buy-and-hold ({alpha:+.2%})')
        else:
            print(f'  [WARN] Alpha < 0: Strategy underperforms buy-and-hold ({alpha:+.2%})')

        if consec > 5:
            print(f'  [WARN] Max consecutive losses > 5: Psychological sustainability risk ({consec})')
        else:
            print(f'  [OK] Max consecutive losses <= 5: Sustainable ({consec})')

        print()
        verdict = 'APPROVE' if (sharpe > 0 and alpha > 0 and dd > -0.30) else 'MODIFY'
        print(f'  VERDICT: {verdict}')
    else:
        print('SKIPPED BACKTEST (invalid DSL)')


if __name__ == '__main__':
    main()
