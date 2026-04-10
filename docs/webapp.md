# Webapp – view and visualize wait times

- **Home:** Latest wait times for every terminal at JFK, LGA, and EWR (general + PreCheck).
- **Terminal detail:** Click a terminal to see a 24-hour chart of general and PreCheck wait times.

## Run locally

From the **project root** (the `tsa` directory):

1. Install dependencies (once):

   ```bash
   pip install -r requirements.txt
   ```

   Or use a venv:

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Start the app:

   ```bash
   python3 app.py
   ```

3. Open in a browser:

   **http://127.0.0.1:5000/**

The app reads from `tsa.db` in the project root. To use another DB:

```bash
TSA_DB_PATH=/path/to/tsa.db python3 app.py
```
