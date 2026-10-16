import os
import io
import zipfile
import requests
import pandas as pd

from dotenv import load_dotenv


# =========================================================
# 1. LOAD ENVIRONMENT VARIABLES
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ENV_FILE = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_FILE)

USERNAME = os.getenv("ENTSOE_USERNAME")
PASSWORD = os.getenv("ENTSOE_PASSWORD")

if not USERNAME:
    raise ValueError(
        f"ENTSOE_USERNAME was not found in: {ENV_FILE}"
    )

if not PASSWORD:
    raise ValueError(
        f"ENTSOE_PASSWORD was not found in: {ENV_FILE}"
    )


# =========================================================
# 2. GET KEYCLOAK ACCESS TOKEN
# =========================================================

TOKEN_URL = (
    "https://keycloak.tp.entsoe.eu/"
    "realms/tp/protocol/openid-connect/token"
)

token_payload = {
    "client_id": "tp-fms-public",
    "grant_type": "password",
    "username": USERNAME,
    "password": PASSWORD,
}

print("\nGetting Keycloak access token...")

token_response = requests.post(
    TOKEN_URL,
    data=token_payload,
    timeout=60
)

token_response.raise_for_status()

token_data = token_response.json()

access_token = token_data["access_token"]

print("Access token obtained successfully.")


# =========================================================
# 3. FMS CONFIGURATION
# =========================================================

FMS_URL = "https://fms.tp.entsoe.eu"

fms_headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
}


# =========================================================
# 4. FMS DATASET FOLDERS
# =========================================================

OUTAGE_FOLDER = (
    "/TP_export/"
    "UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D_r3.1/"
)


CAPACITY_FOLDER = (
    "/TP_export/"
    "ProductionAndGenerationUnits_r3.1/"
)


# =========================================================
# 5. FUNCTION TO LIST ALL ITEMS IN AN FMS FOLDER
# =========================================================

def list_all_fms_items(folder_path, page_size=100):

    all_items = []

    page_index = 0

    while True:

        payload = {
            "path": folder_path,
            "sorterList": [],
            "pageInfo": {
                "pageIndex": page_index,
                "pageSize": page_size
            }
        }

        response = requests.post(
            f"{FMS_URL}/listFolder",
            headers=fms_headers,
            json=payload,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        items = data["contentItemList"]

        all_items.extend(items)

        total = data["pageInfo"]["total"]

        print(
            f"Page {page_index}: "
            f"{len(items)} items "
            f"(collected {len(all_items)}/{total})"
        )

        if len(all_items) >= total:
            break

        page_index += 1

    return all_items


# =========================================================
# 6. GET FILE LISTS
# =========================================================

print("\n" + "=" * 70)
print("GETTING OUTAGE FILE LIST")
print("=" * 70)

outage_items = list_all_fms_items(OUTAGE_FOLDER)


print("\n" + "=" * 70)
print("GETTING INSTALLED CAPACITY FILE LIST")
print("=" * 70)

capacity_items = list_all_fms_items(CAPACITY_FOLDER)


# =========================================================
# 7. SELECT 2025 OUTAGE FILES
# =========================================================

outage_2025 = [
    item
    for item in outage_items
    if item["type"] == "CSV"
    and item["name"].startswith("2025_")
]


print("\n" + "=" * 70)
print("2025 OUTAGE FILES")
print("=" * 70)

for item in outage_2025:
    print(item["name"])

print(f"\nNumber of 2025 outage files found: {len(outage_2025)}")

if len(outage_2025) != 12:
    raise ValueError(
        f"Expected 12 monthly outage files, "
        f"but found {len(outage_2025)}."
    )


# =========================================================
# 8. DOWNLOAD FUNCTION
# =========================================================

def download_fms_csv(folder, filename):

    payload = {
        "folder": folder,
        "filename": filename,
        "downloadAsZip": True,
        "topLevelFolder": "TP_export"
    }

    response = requests.post(
        f"{FMS_URL}/downloadFileContent",
        headers=fms_headers,
        json=payload,
        timeout=300
    )

    response.raise_for_status()

    # -----------------------------------------------------
    # FMS returns ZIP content
    # -----------------------------------------------------

    with zipfile.ZipFile(
        io.BytesIO(response.content)
    ) as z:

        csv_files = [
            name
            for name in z.namelist()
            if name.lower().endswith(".csv")
        ]

        if not csv_files:
            raise ValueError(
                f"No CSV found inside ZIP for {filename}"
            )

        csv_name = csv_files[0]

        print(f"CSV inside ZIP: {csv_name}")

        # -------------------------------------------------
        # Read raw bytes
        # -------------------------------------------------

        with z.open(csv_name) as f:
            raw_data = f.read()

    # -----------------------------------------------------
    # Decode CSV
    # -----------------------------------------------------

    text_data = raw_data.decode(
        "utf-8-sig",
        errors="replace"
    )

    # -----------------------------------------------------
    # Detect delimiter
    # -----------------------------------------------------

    first_line = text_data.splitlines()[0]

    print("First line:")
    print(first_line)

    comma_count = first_line.count(",")
    semicolon_count = first_line.count(";")
    tab_count = first_line.count("\t")

    if semicolon_count > comma_count and semicolon_count > tab_count:
        delimiter = ";"

    elif tab_count > comma_count and tab_count > semicolon_count:
        delimiter = "\t"

    else:
        delimiter = ","

    print(f"Detected delimiter: {repr(delimiter)}")

    # -----------------------------------------------------
    # Read dataframe
    # -----------------------------------------------------

    df = pd.read_csv(
        io.StringIO(text_data),
        sep=delimiter,
        low_memory=False
    )

    return df


# =========================================================
# 9. CREATE OUTPUT FOLDER
# =========================================================

OUTPUT_FOLDER = os.path.join(
    BASE_DIR,
    "ENTSOE_2025_Data"
)

os.makedirs(
    OUTPUT_FOLDER,
    exist_ok=True
)


# =========================================================
# 10. DOWNLOAD 2025 MONTHLY OUTAGES
# =========================================================

print("\n" + "=" * 70)
print("DOWNLOADING 2025 OUTAGE DATA")
print("=" * 70)

outage_dfs = []

# Sort files so January -> December
outage_2025 = sorted(
    outage_2025,
    key=lambda x: x["name"]
)

for i, item in enumerate(
    outage_2025,
    start=1
):

    filename = item["name"]

    print(
        f"\n[{i}/12] Downloading:"
    )

    print(filename)

    monthly_df = download_fms_csv(
        OUTAGE_FOLDER,
        filename
    )

    print(
        f"Rows downloaded: {len(monthly_df):,}"
    )

    outage_dfs.append(
        monthly_df
    )


# =========================================================
# 11. COMBINE ALL 12 MONTHS
# =========================================================

print("\nCombining 12 monthly outage files...")

outage_2025_df = pd.concat(
    outage_dfs,
    ignore_index=True
)

print(
    f"Total 2025 outage rows: "
    f"{len(outage_2025_df):,}"
)


# =========================================================
# 12. SAVE 2025 OUTAGES
# =========================================================

outage_output = os.path.join(
    OUTPUT_FOLDER,
    "ENTSOE_2025_Outages_15.1_ABCD.csv"
)

outage_2025_df.to_csv(
    outage_output,
    index=False
)

print(
    f"\n2025 outage data saved to:\n"
    f"{outage_output}"
)


# =========================================================
# 13. DOWNLOAD INSTALLED CAPACITY
# =========================================================

print("\n" + "=" * 70)
print("DOWNLOADING INSTALLED CAPACITY")
print("=" * 70)

capacity_filename = (
    "ProductionAndGenerationUnits_r3.1.csv"
)

print(
    f"Downloading:\n{capacity_filename}"
)

capacity_df = download_fms_csv(
    CAPACITY_FOLDER,
    capacity_filename
)

print(
    f"Installed capacity rows: "
    f"{len(capacity_df):,}"
)


# =========================================================
# 14. SAVE INSTALLED CAPACITY
# =========================================================

capacity_output = os.path.join(
    OUTPUT_FOLDER,
    "ENTSOE_ProductionAndGenerationUnits_r3.1.csv"
)

capacity_df.to_csv(
    capacity_output,
    index=False
)

print(
    f"\nInstalled capacity data saved to:\n"
    f"{capacity_output}"
)

# =========================================================
# 17. PRINT DATASET INFORMATION
# =========================================================

print("\n" + "=" * 70)
print("DATASET SUMMARY")
print("=" * 70)

print(
    f"\n2025 Outages:"
    f"\nRows    : {len(outage_2025_df):,}"
    f"\nColumns : {len(outage_2025_df.columns)}"
)

print(
    f"\nInstalled Capacity:"
    f"\nRows    : {len(capacity_df):,}"
    f"\nColumns : {len(capacity_df.columns)}"
)

# =========================================================
# 18. PRINT COLUMNS
# =========================================================

print("\n" + "=" * 70)
print("2025 OUTAGE COLUMNS")
print("=" * 70)

for col in outage_2025_df.columns:
    print(col)


print("\n" + "=" * 70)
print("INSTALLED CAPACITY COLUMNS")
print("=" * 70)

for col in capacity_df.columns:
    print(col)

# =========================================================
# 19. DISPLAY FIRST 5 ROWS
# =========================================================

print("\n" + "=" * 70)
print("2025 OUTAGE SAMPLE")
print("=" * 70)

print(
    outage_2025_df.head()
)


print("\n" + "=" * 70)
print("INSTALLED CAPACITY SAMPLE")
print("=" * 70)

print(
    capacity_df.head()
)

# =========================================================
# 20. FINAL MESSAGE
# =========================================================

print("\n" + "=" * 70)
print("EXTRACTION COMPLETED SUCCESSFULLY")
print("=" * 70)

print(
    f"\nOutput folder:\n{OUTPUT_FOLDER}"
)

print("\nFiles created:")

print(
    "1.",
    os.path.basename(outage_output)
)

print(
    "2.",
    os.path.basename(capacity_output)
)