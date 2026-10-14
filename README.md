# Auction XI – Real-Time Fantasy Football Manager

Auction XI is a real-time multi-user fantasy football auction manager built with Python, FastAPI and WebSockets.

The application is designed to manage an entire fantasy football auction from setup to final roster export, supporting multiple teams and devices with synchronized bidding, credits, rosters and auction state.

## Main Features

- Real-time multi-user auction management
- Multiple teams and simultaneous devices
- Admin / auctioneer control panel
- Participant access through private team links
- Live bidding with +1, +5, +10 and custom offers
- Server-side bid ordering
- Automatic credit and roster validation
- Configurable roster slots and starting budgets
- Manual or random player calling
- Random role-by-role auction mode
- Live roster and credit tracking
- Public roster monitoring during the auction
- Player search and availability status
- Player current quotation (Qt.A)
- Release and budget regularization management
- Administrative roster corrections
- Automatic checkpoints and auction recovery
- Post-auction adjustments
- Final roster export
- Leghe Fantacalcio CSV export
- Local-network mode
- Remote auction architecture support

## Technology Stack

- Python
- FastAPI
- SQLAlchemy
- WebSockets
- SQLite
- HTML
- CSS
- JavaScript
- pandas
- openpyxl
- pytest
- Docker

## Project Structure

app/                  Application source code  
tests/                Automated tests  
bootstrap.py          Application bootstrap  
launcher.py           Local launcher  
restore_checkpoint.py Auction recovery utility  
run_windows.bat       Windows launcher  
run_mac_linux.sh      macOS/Linux launcher  
requirements.txt      Python dependencies  
Dockerfile            Container configuration  

## Installation

Clone the repository:

git clone <repository-url>  
cd auction-xi

Install the dependencies:

pip install -r requirements.txt

## Run on Windows

Launch:

run_windows.bat

The admin interface will be available locally at:

http://127.0.0.1:8000

Devices connected to the same local network can access the application through the computer's LAN address.

Example:

http://192.168.x.x:8000

## Auction Workflow

1. Configure the auction
2. Upload the player list
3. Configure teams, budgets and roster limits
4. Start the auction
5. Call players and manage bids in real time
6. Assign players
7. Monitor rosters and remaining credits
8. Complete roster regularization
9. Close the main auction
10. Run post-auction adjustments
11. Export final rosters

## Data Source

Auction XI supports player lists imported from Excel files.

The application does not redistribute third-party fantasy football databases.

Users are responsible for obtaining and using any external player list according to the terms of the respective data provider.

## Testing

Run the automated test suite with:

pytest

The project includes tests covering the main auction workflow, bidding logic, roster validation and administrative operations.

## Project Status

Current release: v1.1.0-rc1

The core local-network auction workflow is operational.

Further improvements and validation are ongoing, especially for remote deployment and third-party roster import/export compatibility.

## Disclaimer

Auction XI is an independent and unofficial project.

It is not affiliated with, endorsed by, or sponsored by Fantacalcio® or Leghe Fantacalcio.

Any trademarks, names or third-party services referenced belong to their respective owners.

## Author

Developed as a personal software and data project for professional portfolio purposes.

## License

License information will be added before the first stable public release.
