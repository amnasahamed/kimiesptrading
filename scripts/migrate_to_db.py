"""
Migration script to move data from JSON files to SQLite database.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import init_db, get_db_session
from src.repositories.position_repository import PositionRepository, TradeRepository


def migrate_positions():
    """Migrate positions from JSON to database."""
    positions_file = Path("positions.json")
    if not positions_file.exists():
        print("No positions.json found")
        return
    
    with open(positions_file, "r") as f:
        positions = json.load(f)
    
    db = get_db_session()
    repo = PositionRepository(db)
    
    count = 0
    for pos_id, pos_data in positions.items():
        try:
            # Convert string timestamps to datetime
            if "entry_time" in pos_data and pos_data["entry_time"]:
                from datetime import datetime
                pos_data["entry_time"] = datetime.fromisoformat(pos_data["entry_time"])
            if "exit_time" in pos_data and pos_data["exit_time"]:
                from datetime import datetime
                pos_data["exit_time"] = datetime.fromisoformat(pos_data["exit_time"])
            
            # Ensure paper_trading field exists
            if "paper_trading" not in pos_data:
                pos_data["paper_trading"] = False
            
            pos_data["id"] = pos_id
            repo.create(pos_data)
            count += 1
        except Exception as e:
            print(f"Error migrating position {pos_id}: {e}")
    
    print(f"Migrated {count} positions")


def migrate_trades():
    """Migrate trades from JSON to database."""
    trades_file = Path("trades_log.json")
    if not trades_file.exists():
        print("No trades_log.json found")
        return
    
    with open(trades_file, "r") as f:
        trades = json.load(f)
    
    db = get_db_session()
    repo = TradeRepository(db)
    
    count = 0
    for trade_data in trades:
        try:
            # Convert timestamp
            if "date" in trade_data and trade_data["date"]:
                from datetime import datetime
                trade_data["date"] = datetime.fromisoformat(trade_data["date"])
            
            # Ensure paper_trading field exists
            if "paper_trading" not in trade_data:
                trade_data["paper_trading"] = False
            
            # Generate ID if not present
            if "id" not in trade_data:
                trade_data["id"] = f"MIGRATED_{count}_{trade_data.get('symbol', 'UNKNOWN')}"
            
            repo.create(trade_data)
            count += 1
        except Exception as e:
            print(f"Error migrating trade: {e}")
    
    print(f"Migrated {count} trades")


def main():
    """Run migration."""
    print("Initializing database...")
    init_db()
    
    print("Migrating positions...")
    migrate_positions()
    
    print("Migrating trades...")
    migrate_trades()
    
    print("Migration complete!")
    print("\nNext steps:")
    print("1. Verify data in database")
    print("2. Update .env file with DATABASE_URL")
    print("3. Run the new application: python -m src.main")


if __name__ == "__main__":
    main()
