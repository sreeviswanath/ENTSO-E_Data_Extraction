import pandas as pd
from pathlib import Path

output_folder = Path("ENTSOE_Output")
output_folder.mkdir(parents=True, exist_ok=True)

# ===============================================
# 1. Loading the data
# ===============================================

df_outages = pd.read_csv("ENTSOE_2025_Data\ENTSOE_2025_Outages_15.1_ABCD.csv")
print("=========== Outages data loaded successfully..... ==========")
# print(df_outages.info())


# ===============================================
# 2. Cleaning the data
# ===============================================

# Dropping unwanted columns
unwanted_columns = ['AreaCode','AreaDisplayName','Reason','Comment']
df_outages = df_outages.drop(unwanted_columns, axis=1)
print("=========== Unwanted columns removed..... ==========")

# Converting date columns to datetime format
date_columns = ['StartOutage(UTC)', 'EndOutage(UTC)', 'StartTimeSeries(UTC)', 'EndTimeSeries(UTC)',
                'VersionPublicationTimestamp(UTC)','UpdateTime(UTC)']
df_outages[date_columns] = df_outages[date_columns].apply(pd.to_datetime, errors='coerce',utc=True)
print("=========== Date columns converted to datetime format..... ==========")

# Convert blank strings to NaN
df_outages = df_outages.replace(r'^\s*$', pd.NA, regex=True)

print("=========== Data info after cleaning..... ==========")
# print(df_outages.info())

# Check for invalid periods where EndOutage(UTC) < StartOutage(UTC)
invalid_periods = df_outages[df_outages["EndOutage(UTC)"] < df_outages["StartOutage(UTC)"]]
if not invalid_periods.empty:
    print("=========== Invalid periods found where EndOutage(UTC) < StartOutage(UTC)..... ==========")
    print(invalid_periods)


# ===============================================
# 3. Applying filters to the data
# ===============================================

# Filtering data based on status = active & AssetType = Production & OldVersion = False & AreaTypeCode != CTA
print("=========== No.of rows before filtering: ", len(df_outages))
df_outages = df_outages[(df_outages['Status'] == 'Active') & 
                        (df_outages['AssetType'] == 'GENERATION') & 
                        (df_outages['OldVersion'] == False) & 
                        (df_outages['AreaTypeCode'] != 'CTA')]

print("=========== Data filtered based on status = Active & AssetType = GENERATION & OldVersion = False & AreaTypeCode != CTA..... ==========")
print("=========== No.of rows after filtering: ", len(df_outages))

# df_outages.to_csv("v1_cleaning_outages_filtered.csv", index=False)
# print("=======&&&&&& Filtered data saved to \"v1_cleaning_outages_filtered.csv\" before dropping missing values....&&&&&&=======")

# Dropping rows with missing values in critical columns
critical_columns = ['InstanceCode','Version','StartTimeSeries(UTC)', 'EndTimeSeries(UTC)','Status','AssetType','ProductionType']
df_outages = df_outages.dropna(subset=critical_columns)
print("=========== Rows with missing values in critical columns dropped..... ==========")
print("=========== No.of rows after dropping missing values: ", len(df_outages))


#==================================================
# 4. Keeping only the latest version of each outage
#==================================================

# Find the maximum Version for each InstanceCode
max_version = (
    df_outages.groupby("InstanceCode", as_index=False)["Version"]
    .max()
    .rename(columns={"Version": "MaxVersion"})
)

print("========== Maximum version calculated for each InstanceCode =========")

# Join the maximum version back to the original data
df_outages = df_outages.merge(max_version,on="InstanceCode",how="inner")

# Keep only rows matching the maximum version
df_outages = df_outages[df_outages["Version"] == df_outages["MaxVersion"]].copy()

# Sort by StartTimeSeries
df_outages = df_outages.sort_values(by=["InstanceCode", "StartTimeSeries(UTC)"]).reset_index(drop=True)

# Remove the temporary column
df_outages = df_outages.drop(columns=["MaxVersion"])

print("=========== Latest versions retained for each InstanceCode ==========")
print("========== Rows after keeping latest versions:", len(df_outages))
print(df_outages.head())
df_outages.to_csv(output_folder / "outages_cleaned.csv", index=False)
print("========&&&&&&& Cleaned data saved to", output_folder / "outages_cleaned.csv", "before exploding &&&&&&=======")

#################################################################################################################

# Round StartTimeSeries and EndTimeSeries to the nearest hour
df_outages["StartTimeSeries(UTC)"] = (df_outages["StartTimeSeries(UTC)"].dt.round("h"))

df_outages["EndTimeSeries(UTC)"] = (df_outages["EndTimeSeries(UTC)"].dt.round("h"))

# print("StartTimeSeries and EndTimeSeries rounded to nearest hour.")
# df_outages.to_csv("v1_cleaning_test_rounded.csv", index=False)

asset_mapping = (df_outages[["AssetCode", "AreaMapCode", "ProductionType"]].dropna().drop_duplicates())

#============================================   
# 5. Exploding the data based on StartTimeSeries and EndTimeSeries
#============================================

df_exploded = df_outages.copy()
print("=========== Exploding the data based on StartTimeSeries and EndTimeSeries..... ==========")
# print(df_exploded.info())

# Generate hourly timestamps:
# StartTimeSeries is inclusive; EndTimeSeries is exclusive
df_exploded["DateTime"] = df_exploded.apply(
    lambda row: pd.date_range(
        start=row["StartTimeSeries(UTC)"],
        end=row["EndTimeSeries(UTC)"],
        freq="h",
        inclusive="left"
    ),
    axis=1
)

# Explode: one row for each asset-hour
df_hourly = df_exploded[["AssetCode", "AvailableCapacity[MW]", "DateTime"]].explode("DateTime")

# Convert capacity to numeric
df_hourly["AvailableCapacity[MW]"] = pd.to_numeric(df_hourly["AvailableCapacity[MW]"],errors="coerce")

# Check for duplicate asset-hour combinations
duplicates = df_hourly.duplicated(subset=["DateTime", "AssetCode"],keep=False)

print("========= Duplicate asset-hour rows:", duplicates.sum())

# Resolve duplicate DateTime + AssetCode combinations
# by keeping the minimum available capacity
df_hourly = (
    df_hourly
    .groupby(["DateTime", "AssetCode"], as_index=False)
    ["AvailableCapacity[MW]"]
    .min()
)

print("========= Duplicate asset-hour combinations resolved using minimum capacity. ==========")
duplicates = df_hourly.duplicated(subset=["DateTime", "AssetCode"],keep=False)

print("========= Duplicate asset-hour rows:", duplicates.sum())

# Pivot: DateTime as rows, AssetCode as columns
df_pivot = (
    df_hourly
    .pivot(
        index="DateTime",
        columns="AssetCode",
        values="AvailableCapacity[MW]"
    )
    .sort_index()
    .rename_axis(columns=None)
    .reset_index()
)

print("========= Hourly outages capacity DataFrame created. ==========")
# print(df_pivot.head())
df_pivot.to_csv(output_folder / "pivoted_hourly_outages.csv", index=False)
print("=======&&&&& Pivoted,hourly-outages capacity DataFrame saved to",output_folder/" pivoted_hourly_outages.csv &&&&&=======")

#########################################################################################################################

# =========================================================
# 6. Fill missing hourly capacity using installed capacity
# =========================================================

# Load the installed-capacity / generation-unit mapping dataset
df_units = pd.read_csv("ENTSOE_2025_Data\ENTSOE_ProductionAndGenerationUnits_r3.1.csv")
print(df_units.head())
# Convert validity dates to UTC datetime
date_cols = ["ValidityPeriodStart(UTC)","ValidityPeriodEnd(UTC)"]
df_units[date_cols] = df_units[date_cols].apply(pd.to_datetime, errors="coerce", utc=True)

# Keep BZN records and exclude cancelled units
df_units = df_units[
    (df_units["AreaTypeCode"] != "CTA") & 
    (df_units["AreaMapCode"] != "DE_AT_LU") &
    (df_units["GenerationUnitStatus"].fillna("").str.upper() != "CANCELLED")
].copy()

# Convert installed capacity to numeric
df_units["GenerationUnitInstalledCapacity[MW]"] = pd.to_numeric(df_units["GenerationUnitInstalledCapacity[MW]"],errors="coerce")

# Keep records with the required fields
df_units = df_units.dropna(subset=["GenerationUnitCode","GenerationUnitType","ValidityPeriodStart(UTC)","GenerationUnitInstalledCapacity[MW]"])

######################################################################################################################################

df_units_fill = df_units.copy()

status = df_units_fill["GenerationUnitStatus"].str.upper()

# 1. COMMISSIONED: Fill blank end dates with 2100-01-01
mask_commissioned = (
    status.eq("COMMISSIONED")
    & df_units_fill["ValidityPeriodEnd(UTC)"].isna()
)

df_units_fill.loc[
    mask_commissioned, "ValidityPeriodEnd(UTC)"
] = pd.Timestamp("2100-01-01", tz="UTC")

 
# 2. DECOMMISSIONED: Fill blank end dates with their start dates
mask_decommissioned = (
    status.eq("DECOMMISSIONED")
    & df_units_fill["ValidityPeriodEnd(UTC)"].isna()
)

df_units_fill.loc[
    mask_decommissioned, "ValidityPeriodEnd(UTC)"
] = df_units_fill.loc[
    mask_decommissioned, "ValidityPeriodStart(UTC)"
]

# 3. DECOMMISSIONED: Set installed capacity to zero
df_units_fill.loc[
    status.eq("DECOMMISSIONED"),
    "GenerationUnitInstalledCapacity[MW]"
] = 0.0

######################################################################################################################################

# Keep only units that have validity start and end timestamps
df_units_fill = df_units_fill.dropna(
    subset=["ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)"]
).copy()

start_date = df_pivot["DateTime"].min()
end_date = df_pivot["DateTime"].max()

# Keep units whose validity periods overlap the required date range
df_units_fill = df_units_fill[
    (df_units_fill["ValidityPeriodStart(UTC)"] < end_date)
    & (df_units_fill["ValidityPeriodEnd(UTC)"] > start_date)
].copy()

# Generate hourly timestamps for each unit and exploding
df_units_fill["Cap_Dates"] = df_units_fill.apply(
    lambda row: pd.date_range(
        start=max(row["ValidityPeriodStart(UTC)"], start_date),
        end=min(row["ValidityPeriodEnd(UTC)"], end_date),
        freq="h"
    ),
    axis=1
)

# Expand the timestamp lists into individual rows
df_units_hourly = df_units_fill.explode("Cap_Dates").reset_index(drop=True)

###########################################################################################################################################

df_units_hourly = df_units_hourly.sort_values(
    ["ValidityPeriodEnd(UTC)", "ValidityPeriodStart(UTC)"],
    ascending=[False, False],
    na_position="last"
)

df_units_hourly = df_units_hourly.drop_duplicates(
    subset=["GenerationUnitCode", "Cap_Dates"],
    keep="first"
).copy()


# Create a lookup of installed capacity by asset and validity timestamp
capacity_lookup = {
    asset: group.set_index("Cap_Dates")["GenerationUnitInstalledCapacity[MW]"]
    for asset, group in df_units_hourly.groupby("GenerationUnitCode", sort=False)
}

# Keep the original pivot unchanged
df_pivot_filled = df_pivot.set_index("DateTime").copy()

# Fill missing hourly capacity using the valid installed capacity
filled_cells = 0

for asset in df_pivot_filled.columns:
    if asset in capacity_lookup:
        installed_capacity = capacity_lookup[asset].reindex(
            df_pivot_filled.index
        )

        missing_before = df_pivot_filled[asset].isna().sum()

        df_pivot_filled[asset] = df_pivot_filled[asset].fillna(
            installed_capacity
        )

        filled_cells += missing_before - df_pivot_filled[asset].isna().sum()

# Restore DateTime as a regular column
df_pivot_filled = df_pivot_filled.reset_index()
df_pivot_filled = df_pivot_filled.copy()

# print("Hourly capacity shape:", df_pivot_filled.shape)
# print("Missing values filled:", filled_cells)
# print("Remaining missing asset-hour values:",
#       df_pivot_filled.drop(columns="DateTime").isna().sum().sum())

# # Confirm the original pivot was not modified
# print("Original shape:", df_pivot.shape)
# print("Filled shape:", df_pivot_filled.shape)

# Save the result
df_pivot_filled.to_csv(output_folder / "hourly_capacity_filled.csv", index=False)
print("\n========&&&&&&& Installed-capacity filled hourly-data saved to",output_folder/"hourly_capacity_filled.csv &&&&&&=======")

###################################################################################################################################################
###################################################################################################################################################
###################################################################################################################################################

df_mapping = df_units_hourly[["GenerationUnitCode","Cap_Dates","AreaMapCode","GenerationUnitType"]].copy()
df_mapping = df_mapping.rename(columns={"Cap_Dates": "DateTime"})

# Ensure both DataFrames use matching UTC timestamps before merging
df_pivot_filled["DateTime"] = pd.to_datetime(
    df_pivot_filled["DateTime"], utc=True
)
df_mapping["DateTime"] = pd.to_datetime(
    df_mapping["DateTime"], utc=True
)

# 2. Convert the hourly wide-format data to long format and merge
df_hourly_long = (
    df_pivot_filled
    .melt(
        id_vars="DateTime",
        var_name="GenerationUnitCode",
        value_name="AvailableCapacity_MW"
    )
    .merge(
        df_mapping,
        on=["GenerationUnitCode", "DateTime"],
        how="left"
    )
)

df_hourly_long = df_hourly_long.dropna(
    subset=["AreaMapCode", "GenerationUnitType"]
).copy()


# Fuel mapping
fuel_types = {
    "Fossil Gas": "Gas",
    "Fossil Hard coal": "Coal",
    "Fossil Coal-derived gas": "Gas",
    'Hydro Pumped Storage': 'Pump',
    'Hydro Water Reservoir': 'Reservoir',
    'Fossil Oil' : 'Oil',
    'Fossil Brown coal/Lignite' : 'Lignite',
    'Hydro Run-of-river and pondage': 'ROR',
    'Nuclear' : 'Nuclear',
    'Solar' : 'Solar',
    'Other' : 'OtherRenewable',
    'Biomass' : 'Biomass',
    'Wind Offshore': 'WindOffshore',
    'Wind Onshore': 'WindOnshore',
    'Energy storage':'Storage',
    'Fossil Oil shale':'Oil',
    'Fossil Peat':'Coal',
    'Waste':'Waste'
}

df_hourly_long["GenerationUnitType"] = (df_hourly_long["GenerationUnitType"].replace(fuel_types))

# Zone mapping
zone_map = {
    "SE": ["SE1", "SE2", "SE3", "SE4", "SE"],
    "IT": ["IT-CSOUTH", "IT-CNORTH", "IT-NORTH", "IT-SOUTH", "IT-Sardinia", "IT-Sicily", "IT-Calabria", "IT"],
    "NO": ["NO1", "NO2", "NO3", "NO4", "NO5", "NO"],
    "DK": ["DK1", "DK2"],
    "DE": ["DE_LU"]
}

zone_lookup = {
    zone: parent
    for parent, zones in zone_map.items()
    for zone in zones
}

df_hourly_long["AreaMapCode"] = (df_hourly_long["AreaMapCode"].replace(zone_lookup))


# Convert UTC timestamps to Amsterdam local time
df_hourly_long["DateTime"] = (
    df_hourly_long["DateTime"].dt.tz_convert("Europe/Amsterdam")
)

# print(df_hourly_long[(df_hourly_long["AreaMapCode"] == "DE") & (df_hourly_long["GenerationUnitCode"]=="11WD4AL1U1C2---O")].head(30))
df_hourly_long.to_csv("Testing_mean_of_24_hours.csv",index=False)
print("========&&&&&&& Hourly capacity for assets saved to Testing_mean_of_24_hours.csv &&&&&=========")
# print("Unique fuel types :- ",df_hourly_long["GenerationUnitType"].unique())
# print("Unique area mapcodes :- ",df_hourly_long["AreaMapCode"].unique())


# Convert timestamps to the start of each Amsterdam local day
df_hourly_long["DateTime"] = ( df_hourly_long["DateTime"].dt.floor("D") )

# Calculate daily average capacity for each asset
df_daily_assets = (
    df_hourly_long
    .groupby(
        ["GenerationUnitCode", "AreaMapCode", "DateTime", "GenerationUnitType"],
        as_index=False
    )["AvailableCapacity_MW"]
    .mean()
)

# To check specific asset,specific date hourly to daily capacity change
# print("\n******* Testing hourly to daily conversion ! ******\n")
# asset = "11WD4AL1U1C2---O"

# df_check = df_hourly_long[
#     (df_hourly_long["GenerationUnitCode"] == asset) & 
#     (df_hourly_long["DateTime"].dt.tz_convert("Europe/Amsterdam").dt.date == pd.Timestamp("2025-01-09").date())
# ].copy()

# print(df_check[["DateTime", "AvailableCapacity_MW", "AreaMapCode", "GenerationUnitType"]].sort_values("DateTime").to_string(index=False))

# print("\nNumber of rows:", len(df_check))
# print("Sum of capacity:", df_check["AvailableCapacity_MW"].sum())
# print("Mean capacity:", df_check["AvailableCapacity_MW"].mean())
# print("Missing capacity values:", df_check["AvailableCapacity_MW"].isna().sum())
# print(df_daily_assets[(df_daily_assets["AreaMapCode"] == "DE") & (df_daily_assets["GenerationUnitCode"]=="11WD4AL1U1C2---O")].head(15))

df_daily_assets.to_csv("Testing_daily_cap_per_asset.csv",index=False)
print("========&&&&&&& Daily capacity for assets saved to Testing_daily_cap_per_asset.csv &&&&&=========")

##############################################################################################################################################################
##############################################################################################################################################################
##############################################################################################################################################################

# Aggregating daily capacity based on area and fuel type 

df_daily_grouped = (df_daily_assets.groupby(["AreaMapCode", "DateTime", "GenerationUnitType"],as_index=False)["AvailableCapacity_MW"]
    .sum(min_count=1).round())

# Area_fuel column creation

df_daily_grouped["Area_Fuel"] = (df_daily_grouped["GenerationUnitType"]+ "_" + df_daily_grouped["AreaMapCode"])

# Pivoting to final format

df_final = (
    df_daily_grouped
    .pivot(
        index="DateTime",
        columns="Area_Fuel",
        values="AvailableCapacity_MW"
    )
    .reset_index()
)

df_final.columns.name = None

df_final = df_final[
    ["DateTime"] +
    sorted(
        [col for col in df_final.columns if col != "DateTime"],
        key=lambda col: col.split("_")[-1]
    )
]

print(df_final.head())
print("Date range:", df_final["DateTime"].min(), "to", df_final["DateTime"].max())

df_final.to_csv(output_folder/"ENTSOE_2025_Daily_Area_Fuel_Capacity.csv",index=False)
print("\n======&&&&&& Daily capacity for area per fuel type saved to ENTSOE_2025_Daily_Area_Fuel_Capacity.csv &&&&&&======\n")

###########################################################################################################################
###########################################################################################################################
###########################################################################################################################

# 1. Available capacity: wide to long
df_available = df_final.melt(
    id_vars="DateTime",
    var_name="Fuel_Area",
    value_name="AvailableCapacity_MW"
)

df_available[["GenerationUnitType", "AreaMapCode"]] = (
    df_available["Fuel_Area"].str.rsplit("_", n=1, expand=True)
)
df_available["DateTime"] = pd.to_datetime(df_available["DateTime"]).dt.date


# 2. Daily installed capacity from existing hourly data
df_installed_daily = df_units_hourly.copy()

df_installed_daily["DateTime"] = (
    pd.to_datetime(df_installed_daily["Cap_Dates"], utc=True)
    .dt.tz_convert("Europe/Amsterdam")
    .dt.date
)

# Apply the SAME fuel mapping
df_installed_daily["GenerationUnitType"] = (
    df_installed_daily["GenerationUnitType"].replace(fuel_types)
)

# Apply the SAME zone mapping
df_installed_daily["AreaMapCode"] = (
    df_installed_daily["AreaMapCode"].replace(zone_lookup)
)

# Aggregate installed capacity by date, area and renamed fuel
df_installed_daily = (
    df_installed_daily
    .groupby(
        ["DateTime", "AreaMapCode", "GenerationUnitType"],
        as_index=False
    )["GenerationUnitInstalledCapacity[MW]"]
    .sum(min_count=1)
    .rename(columns={
        "GenerationUnitInstalledCapacity[MW]": "InstalledCapacity_MW"
    })
)
print("========= Calculated total daily installed capacity per fuel/area ========")
print(df_installed_daily.head(10))
df_installed_daily.to_csv("Total_installed_cap_test.csv",index=False)

# 3. Merge and calculate AF
df_af = df_available.merge(
    df_installed_daily,
    on=["DateTime", "AreaMapCode", "GenerationUnitType"],
    how="left"
)

df_af["AF_Percent"] = (
    df_af["AvailableCapacity_MW"]
    .div(df_af["InstalledCapacity_MW"].where(df_af["InstalledCapacity_MW"] > 0))
    .mul(100).round(2)
)


# 4. Pivot back to df_final format
df_af_final = (
    df_af.assign(Fuel_Area=df_af["GenerationUnitType"] + "_" + df_af["AreaMapCode"])
    .pivot(index="DateTime", columns="Fuel_Area", values="AF_Percent")
    .reset_index()
)

df_af_final.columns.name = None
df_af_final = df_af_final[
    ["DateTime"] + sorted(
        [c for c in df_af_final.columns if c != "DateTime"],
        key=lambda c: c.rsplit("_", 1)[1]
    )
]


df_af_final.to_csv(
    output_folder / "ENTSOE_2025_Daily_Availability_Factor.csv",
    index=False
)
print("\n======&&&&& Availability Factor saved to ENTSOE_2025_Daily_Availability_Factor.csv\n")
print(df_af_final.head())
print("Final AF shape:", df_af_final.shape)

# df_available = df_final.copy()
# # Convert daily available capacity from wide to long format
# df_available = df_available.melt(
#     id_vars="DateTime",
#     var_name="Fuel_Area",
#     value_name="AvailableCapacity_MW"
# )

# # Split column name into fuel type and area code
# df_available[["GenerationUnitType", "AreaMapCode"]] = (
#     df_available["Fuel_Area"].str.rsplit("_", n=1, expand=True)
# )

# df_available["DateTime"] = pd.to_datetime(
#     df_available["DateTime"]
# ).dt.date


# # Select the required installed-capacity columns
# df_installed = df_units[
#     [
#         "GenerationUnitCode",
#         "GenerationUnitInstalledCapacity[MW]",
#         "AreaMapCode",
#         "GenerationUnitType",
#         "ValidityPeriodStart(UTC)",
#         "ValidityPeriodEnd(UTC)"
#     ]
# ].copy()

# # Convert validity dates to Amsterdam local dates
# for col in ["ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)"]:
#     df_installed[col] = (
#         pd.to_datetime(df_installed[col], utc=True)
#         .dt.tz_convert("Europe/Amsterdam")
#         .dt.date
#     )

# # Keep records that overlap 2025
# year_start = pd.Timestamp("2025-01-01").date()
# year_end = pd.Timestamp("2025-12-31").date()

# df_installed = df_installed[
#     (df_installed["ValidityPeriodStart(UTC)"] <= year_end) &
#     (
#         df_installed["ValidityPeriodEnd(UTC)"].isna() |
#         (df_installed["ValidityPeriodEnd(UTC)"] >= year_start)
#     )
# ].copy()

# # Restrict validity dates to 2025
# df_installed["StartDate"] = df_installed[
#     "ValidityPeriodStart(UTC)"
# ].apply(lambda x: max(x, year_start))

# df_installed["EndDate"] = df_installed[
#     "ValidityPeriodEnd(UTC)"
# ].apply(
#     lambda x: year_end if pd.isna(x) else min(x, year_end)
# )

# # Create one record per unit per valid day
# df_installed["DateTime"] = df_installed.apply(
#     lambda row: pd.date_range(
#         start=row["StartDate"],
#         end=row["EndDate"],
#         freq="D"
#     ).date,
#     axis=1
# )

# df_installed_daily = df_installed.explode("DateTime")

# # Rename capacity column
# df_installed_daily = df_installed_daily.rename(
#     columns={
#         "GenerationUnitInstalledCapacity[MW]": "InstalledCapacity_MW"
#     }
# )

# # Aggregate installed capacity by date, area and fuel
# df_installed_daily = (
#     df_installed_daily
#     .groupby(
#         ["DateTime", "AreaMapCode", "GenerationUnitType"],
#         as_index=False
#     )["InstalledCapacity_MW"]
#     .sum(min_count=1)
# )

# print(df_installed_daily.head())




# # Merge available and installed capacity
# df_af = df_available.merge(
#     df_installed_daily,
#     on=["DateTime", "AreaMapCode", "GenerationUnitType"],
#     how="left"
# )

# # Calculate availability factor (%)
# df_af["AF_Percent"] = (
#     df_af["AvailableCapacity_MW"]
#     .div(df_af["InstalledCapacity_MW"].where(
#         df_af["InstalledCapacity_MW"] > 0
#     ))
#     .mul(100)
# )

# # Round results
# df_af["AF_Percent"] = df_af["AF_Percent"].round(2)

# # Arrange columns
# df_af = df_af[
#     [
#         "DateTime",
#         "AreaMapCode",
#         "GenerationUnitType",
#         "AvailableCapacity_MW",
#         "InstalledCapacity_MW",
#         "AF_Percent"
#     ]
# ].sort_values(
#     ["AreaMapCode", "GenerationUnitType", "DateTime"]
# )

# # Create column names in Fuel_Area format
# df_af["Fuel_Area"] = (
#     df_af["GenerationUnitType"] + "_" + df_af["AreaMapCode"]
# )

# # Pivot AF values into wide format
# df_af_final = (
#     df_af.pivot(
#         index="DateTime",
#         columns="Fuel_Area",
#         values="AF_Percent"
#     )
#     .reset_index()
# )

# # Remove columns index name
# df_af_final.columns.name = None

# # Sort columns by area code
# df_af_final = df_af_final[
#     ["DateTime"] +
#     sorted(
#         [col for col in df_af_final.columns if col != "DateTime"],
#         key=lambda col: col.rsplit("_", 1)[1]
#     )
# ]

# # Save output
# df_af_final.to_csv(
#     output_folder / "ENTSOE_2025_Daily_Availability_Factor.csv",
#     index=False
# )

# print(df_af_final.head())
# print("Final AF shape:", df_af_final.shape)
