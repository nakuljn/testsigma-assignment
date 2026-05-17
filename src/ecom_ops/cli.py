"""
CLI entry point for the daily ops cycle.

Usage:
    ecom-ops                        # uses today's date, provider from env
    ecom-ops --date 2026-05-17
    ecom-ops --provider anthropic
    ecom-ops --print-report
    ecom-ops --fast                 # skip web search (much faster)
"""
import argparse
import asyncio
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ecom-ops",
        description="Agentic E-Commerce Operations Manager — daily cycle",
    )
    parser.add_argument(
        "--date", default=None,
        help="Run date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--provider", choices=["openai", "anthropic"], default=None,
        help="LLM provider override (overrides MODEL_PROVIDER env var).",
    )
    parser.add_argument(
        "--print-report", action="store_true",
        help="Print the full Markdown report to stdout after the run.",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Skip competitor web search (faster demo; demand-only pricing).",
    )
    args = parser.parse_args()

    if args.provider:
        os.environ["MODEL_PROVIDER"] = args.provider
    if args.fast:
        os.environ["SKIP_WEB_SEARCH"] = "1"
        os.environ["BATCH_LLM"] = "1"

    from ecom_ops.config.settings import BATCH_LLM, MODEL_PROVIDER, OUTPUT_DIR, SKIP_WEB_SEARCH
    from ecom_ops.graph.ops_graph import run_daily_cycle

    provider = args.provider or MODEL_PROVIDER
    run_date = args.date

    print("=" * 60)
    print("  Agentic E-Commerce Operations Manager")
    print("=" * 60)
    print(f"  Run date     : {run_date or 'today'}")
    print(f"  Provider     : {provider}")
    print(f"  Web search   : {'off (--fast)' if SKIP_WEB_SEARCH else 'on (max 3 SKUs, 15s timeout each)'}")
    print(f"  LLM mode     : {'batched (~5 calls)' if BATCH_LLM else 'per-SKU (slower)'}")
    print("=" * 60)
    print()
    est = "30–90 sec" if BATCH_LLM else "2–5 min"
    print(f"Running pipeline — progress below (est. {est}):")
    print()

    try:
        final_state = asyncio.run(run_daily_cycle(run_date, fast=args.fast))
    except Exception as exc:
        print()
        print("=" * 60)
        print("  Run FAILED")
        print("=" * 60)
        print(f"  Error: {exc}")
        print()
        print("  Common fixes:")
        print("  - Check OPENAI_API_KEY in .env")
        print("  - Try: make demo FAST=1   or   python run.py --fast")
        print("  - Ensure you ran: make setup  (uses .venv)")
        raise SystemExit(1) from exc

    report_md = final_state.get("report_markdown", "")
    committed = final_state.get("committed_changes", [])
    conflicts = final_state.get("conflicts", [])
    restock = final_state.get("restock_decisions", [])
    pricing = final_state.get("price_decisions", [])
    issues = final_state.get("product_issues", [])
    campaigns = final_state.get("campaign_drafts", [])
    suppressed = sum(1 for c in campaigns if c.suppressed)

    from datetime import date
    report_date = final_state.get("run_date") or str(date.today())

    print()
    print("=" * 60)
    print("  Run complete!")
    print(f"  Restock decisions     : {len(restock)}")
    print(f"  Price changes         : {len(pricing)}")
    print(f"  Product issues        : {len(issues)}")
    print(f"  Campaigns (active)    : {len(campaigns) - suppressed}")
    print(f"  Campaigns (suppressed) : {suppressed}")
    print(f"  Conflicts resolved    : {len(conflicts)}")
    print(f"  Committed changes     : {len(committed)}")
    print(f"\n  Report saved to       : {OUTPUT_DIR / f'daily_ops_{report_date}.md'}")
    print("=" * 60)

    if args.print_report:
        print("\n" + report_md)
