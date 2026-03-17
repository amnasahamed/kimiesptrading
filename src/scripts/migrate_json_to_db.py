"""
One-time JSON → SQLite migration script.

Usage:
    python src/scripts/migrate_json_to_db.py [--dry-run]

Properties:
- Idempotent (upserts, safe to re-run)
- Dry-run flag previews without writing
- Summary output: N migrated, M skipped, K errors
- Archives original JSON files with .bak extension after successful migration
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running as a script from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.database import (
    init_db, get_db_session,
    Position, Trade, Signal, IncomingAlert,
    Insight, TurboQueueItem, ErrorLog,
)


ROOT = Path(__file__).parent.parent.parent  # project root


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠ Could not load {path}: {e}")
        return None


def _archive(path: Path, dry_run: bool):
    if dry_run or not path.exists():
        return
    bak = path.with_suffix(path.suffix + ".migrated.bak")
    path.rename(bak)
    print(f"  📦 Archived {path.name} → {bak.name}")


def _parse_dt(s):
    """Parse ISO datetime string, return None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def migrate_trades(db, dry_run: bool):
    path = ROOT / "trades_log.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ trades_log.json not found, skipping")
        return 0, 0, 0
    if not isinstance(data, list):
        data = list(data.values())

    migrated = skipped = errors = 0
    for item in data:
        trade_id = item.get("id") or item.get("order_id")
        if not trade_id:
            skipped += 1
            continue
        existing = db.query(Trade).filter_by(id=trade_id).first()
        if existing:
            skipped += 1
            continue
        try:
            trade = Trade(
                id=trade_id,
                date=_parse_dt(item.get("date")) or datetime.utcnow(),
                symbol=(item.get("symbol") or "").upper(),
                action=item.get("action", "BUY"),
                entry_price=float(item.get("entry_price") or item.get("price") or 0),
                exit_price=item.get("exit_price"),
                stop_loss=float(item.get("stop_loss") or item.get("sl") or 0),
                target=float(item.get("target") or item.get("tp") or 0),
                quantity=int(item.get("quantity") or 0),
                risk_amount=item.get("risk_amount"),
                risk_reward=item.get("risk_reward"),
                atr=item.get("atr"),
                order_id=item.get("order_id"),
                order_status=item.get("order_status"),
                sl_order_id=item.get("sl_order_id"),
                tp_order_id=item.get("tp_order_id"),
                status=item.get("status", "OPEN"),
                pnl=float(item.get("pnl") or 0),
                alert_name=item.get("alert_name") or item.get("scan_name"),
                scan_name=item.get("scan_name"),
                paper_trading=bool(item.get("paper_trading", False)),
                context=item.get("context"),
            )
            if not dry_run:
                db.add(trade)
            migrated += 1
        except Exception as e:
            print(f"  ✗ Trade {trade_id}: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_positions(db, dry_run: bool):
    path = ROOT / "positions.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ positions.json not found, skipping")
        return 0, 0, 0

    # positions.json is a dict: {id: {...}}
    if isinstance(data, list):
        items = {str(i): v for i, v in enumerate(data)}
    else:
        items = data

    migrated = skipped = errors = 0
    for pos_id, item in items.items():
        existing = db.query(Position).filter_by(id=pos_id).first()
        if existing:
            skipped += 1
            continue
        try:
            pos = Position(
                id=pos_id,
                symbol=(item.get("symbol") or "").upper(),
                quantity=int(item.get("quantity") or 0),
                entry_price=float(item.get("entry_price") or 0),
                entry_order_id=item.get("entry_order_id"),
                sl_price=float(item.get("sl_price") or item.get("stop_loss") or 0),
                tp_price=float(item.get("tp_price") or item.get("target") or 0),
                sl_order_id=item.get("sl_order_id"),
                tp_order_id=item.get("tp_order_id"),
                status=item.get("status", "OPEN"),
                entry_time=_parse_dt(item.get("entry_time")),
                exit_price=item.get("exit_price"),
                exit_time=_parse_dt(item.get("exit_time")),
                exit_reason=item.get("exit_reason"),
                pnl=float(item.get("pnl") or 0),
                paper_trading=bool(item.get("paper_trading", False)),
                external=bool(item.get("external", False)),
                source=item.get("source", "BOT"),
                clubbed=bool(item.get("clubbed", False)),
                club_count=int(item.get("club_count") or 1),
                component_trades=item.get("component_trades") or [],
                partial_exits=item.get("partial_exits") or [],
                highest_r=float(item.get("highest_r") or 0),
            )
            if not dry_run:
                db.add(pos)
            migrated += 1
        except Exception as e:
            print(f"  ✗ Position {pos_id}: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_signals(db, dry_run: bool):
    path = ROOT / "signals_log.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ signals_log.json not found, skipping")
        return 0, 0, 0
    if not isinstance(data, list):
        data = list(data.values())

    migrated = skipped = errors = 0
    for item in data:
        try:
            sig = Signal(
                timestamp=_parse_dt(item.get("timestamp")) or datetime.utcnow(),
                symbol=(item.get("symbol") or "").upper(),
                status=item.get("status", "RECEIVED"),
                reason=item.get("reason"),
                signal_metadata=item.get("metadata") or {},
                paper_trading=bool(item.get("paper_trading", False)),
            )
            if not dry_run:
                db.add(sig)
            migrated += 1
        except Exception as e:
            print(f"  ✗ Signal: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_incoming_alerts(db, dry_run: bool):
    path = ROOT / "incoming_alerts.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ incoming_alerts.json not found, skipping")
        return 0, 0, 0
    if not isinstance(data, list):
        data = list(data.values())

    migrated = skipped = errors = 0
    for item in data:
        alert_id = item.get("id")
        if not alert_id:
            skipped += 1
            continue
        existing = db.query(IncomingAlert).filter_by(id=alert_id).first()
        if existing:
            skipped += 1
            continue
        try:
            alert = IncomingAlert(
                id=alert_id,
                received_at=_parse_dt(item.get("received_at") or item.get("timestamp")) or datetime.utcnow(),
                alert_type=item.get("alert_type", "json"),
                symbols=item.get("symbols") or [],
                raw_payload=item.get("raw_payload") or {},
                source_ip=item.get("source_ip"),
                headers=item.get("headers") or {},
                processing_status=item.get("processing_status", "processed"),
                processing_result=item.get("processing_result"),
                latency_ms=item.get("total_latency_ms") or item.get("latency_ms"),
            )
            if not dry_run:
                db.add(alert)
            migrated += 1
        except Exception as e:
            print(f"  ✗ IncomingAlert {alert_id}: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_insights(db, dry_run: bool):
    path = ROOT / "trade_insights.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ trade_insights.json not found, skipping")
        return 0, 0, 0

    # trade_insights.json is a dict: {symbol: {stats...}, "daily_stats": {...}}
    migrated = skipped = errors = 0
    for symbol, stats in data.items():
        if symbol == "daily_stats" or not isinstance(stats, dict):
            skipped += 1
            continue
        existing = db.query(Insight).filter_by(symbol=symbol).first()
        if existing:
            skipped += 1
            continue
        try:
            insight = Insight(
                symbol=symbol.upper(),
                trades=int(stats.get("total_trades") or stats.get("trades") or 0),
                wins=int(stats.get("winning_trades") or stats.get("wins") or 0),
                losses=int(stats.get("losing_trades") or stats.get("losses") or 0),
                total_pnl=float(stats.get("total_pnl") or 0),
                avg_pnl=float(stats.get("avg_pnl") or 0),
                win_rate=float(stats.get("win_rate") or 0),
                avg_hold_minutes=float(stats.get("avg_hold_minutes") or 0),
                best_pnl=float(stats.get("best_trade") or stats.get("best_pnl") or 0),
                worst_pnl=float(stats.get("worst_trade") or stats.get("worst_pnl") or 0),
                extra=stats,
            )
            if not dry_run:
                db.add(insight)
            migrated += 1
        except Exception as e:
            print(f"  ✗ Insight {symbol}: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_turbo_queue(db, dry_run: bool):
    path = ROOT / "turbo_queue.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ turbo_queue.json not found, skipping")
        return 0, 0, 0
    if not isinstance(data, list):
        data = list(data.values()) if isinstance(data, dict) else []

    migrated = skipped = errors = 0
    for item in data:
        item_id = item.get("id")
        if not item_id:
            skipped += 1
            continue
        existing = db.query(TurboQueueItem).filter_by(id=item_id).first()
        if existing:
            skipped += 1
            continue
        try:
            entry = TurboQueueItem(
                id=item_id,
                symbol=(item.get("symbol") or "").upper(),
                scan_name=item.get("scan_name"),
                alert_price=item.get("alert_price") or item.get("price"),
                created_at=_parse_dt(item.get("created_at") or item.get("timestamp")) or datetime.utcnow(),
                status=item.get("status", "done"),
                timeframes_confirmed=item.get("timeframes_confirmed") or [],
                timeframes_required=item.get("timeframes_required") or [],
                result=str(item.get("result") or ""),
                processed_at=_parse_dt(item.get("processed_at")),
                extra=item,
            )
            if not dry_run:
                db.add(entry)
            migrated += 1
        except Exception as e:
            print(f"  ✗ TurboQueue {item_id}: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def migrate_error_log(db, dry_run: bool):
    path = ROOT / "error_log.json"
    data = _load_json(path)
    if data is None:
        print("  ⏭ error_log.json not found, skipping")
        return 0, 0, 0
    if not isinstance(data, list):
        data = list(data.values()) if isinstance(data, dict) else []

    migrated = skipped = errors = 0
    for item in data:
        try:
            entry = ErrorLog(
                timestamp=_parse_dt(item.get("timestamp")) or datetime.utcnow(),
                category=item.get("category", "unknown"),
                message=str(item.get("message") or item.get("error") or ""),
                details=item.get("details") or {},
                resolved=bool(item.get("resolved", False)),
            )
            if not dry_run:
                db.add(entry)
            migrated += 1
        except Exception as e:
            print(f"  ✗ ErrorLog: {e}")
            errors += 1

    if not dry_run:
        db.commit()
        _archive(path, dry_run)
    return migrated, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Migrate JSON files to SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    dry = args.dry_run
    if dry:
        print("🔍 DRY RUN — no data will be written\n")
    else:
        print("🚀 Migrating JSON → SQLite\n")

    init_db()
    db = get_db_session()

    steps = [
        ("trades_log.json → trades", migrate_trades),
        ("positions.json → positions", migrate_positions),
        ("signals_log.json → signals", migrate_signals),
        ("incoming_alerts.json → incoming_alerts", migrate_incoming_alerts),
        ("trade_insights.json → insights", migrate_insights),
        ("turbo_queue.json → turbo_queue", migrate_turbo_queue),
        ("error_log.json → error_log", migrate_error_log),
    ]

    total_m = total_s = total_e = 0
    for label, fn in steps:
        print(f"📂 {label}")
        m, s, e = fn(db, dry)
        print(f"   ✓ {m} migrated, {s} skipped, {e} errors")
        total_m += m
        total_s += s
        total_e += e

    db.close()
    print(f"\n{'DRY RUN ' if dry else ''}Summary: {total_m} migrated, {total_s} skipped, {total_e} errors")
    if dry:
        print("Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
