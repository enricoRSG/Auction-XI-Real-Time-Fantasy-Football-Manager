import sys
import os
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Existing module setup resets the database: keep all tests away from real auctions.
TEST_DATA = tempfile.TemporaryDirectory(prefix='auctionxi-tests-')
os.environ['AUCTIONXI_DB_PATH'] = str(Path(TEST_DATA.name) / 'fantacalcio.db')
os.environ['AUCTIONXI_EXPORT_DIR'] = str(Path(TEST_DATA.name) / 'exports')

def pytest_sessionfinish(session, exitstatus):
    from app.database import engine
    engine.dispose()
    TEST_DATA.cleanup()
