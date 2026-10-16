import pandas as pd

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

df_outages.to_csv("v1_cleaning_outages_filtered.csv", index=False)
print("=======&&&&&& Filtered data saved to v1_cleaning_outages_filtered.csv before dropping missing values....&&&&&&=======")

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

df_outages.to_csv("v1_cleaning_outages_cleaned.csv", index=False)   
print("========&&&&&&& Cleaned data saved to v1_cleaning_outages_cleaned.csv before exploding &&&&&&=======")


# Round StartTimeSeries and EndTimeSeries to the nearest hour
df_outages["StartTimeSeries(UTC)"] = (df_outages["StartTimeSeries(UTC)"].dt.round("h"))

df_outages["EndTimeSeries(UTC)"] = (df_outages["EndTimeSeries(UTC)"].dt.round("h"))

# print("StartTimeSeries and EndTimeSeries rounded to nearest hour.")
# df_outages.to_csv("v1_cleaning_test_rounded.csv", index=False)

asset_mapping = (df_outages[["AssetCode", "AreaMapCode", "ProductionType"]].dropna().drop_duplicates())

#=====================================================================================================
#============================================   
# 5. Exploding the data based on StartTimeSeries and EndTimeSeries
#============================================
#=====================================================================================================

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

# df_hourly.to_csv("v1_cleaning_test_hourly.csv", index=False)

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
df_pivot.to_csv("v1_cleaning_test_hourly_pivoted.csv", index=False)
print("=======&&&&& Pivoted hourly outages capacity DataFrame saved to v1_cleaning_test_hourly_pivoted.csv &&&&&=======")

#########################################################################################################################
#########################################################################################################################
#########################################################################################################################

# =========================================================
# 6. Fill missing hourly capacity using installed capacity
# =========================================================

# Load the installed-capacity / generation-unit mapping dataset
df_units = pd.read_csv("ENTSOE_2025_Data\ENTSOE_ProductionAndGenerationUnits_r3.1.csv")


print("===============& & & & & & & & &********************& & & & & & & & & & & & &***************")
# print("Info about hourly outages capacity pivoted DataFrame with missing values:")
# print(df_pivot.info())
# print(df_pivot.head())
# print("Info about installed-capacity / generation-unit mapping DataFrame:")
# print(df_units.info())
# print(df_units.head())
print("===============& & & & & & & & &********************& & & & & & & & & & & & &***************")


# Convert validity dates to UTC datetime
date_cols = ["ValidityPeriodStart(UTC)","ValidityPeriodEnd(UTC)"]
df_units[date_cols] = df_units[date_cols].apply(pd.to_datetime, errors="coerce", utc=True)

# Keep BZN records and exclude cancelled units
df_units = df_units[
    (df_units["AreaTypeCode"] != "CTA") & (df_units["AreaMapCode"] != "DE_AT_LU") &
    (
        df_units["GenerationUnitStatus"]
        .fillna("")
        .str.upper() != "CANCELLED"
    )
].copy()

# Convert installed capacity to numeric
df_units["GenerationUnitInstalledCapacity[MW]"] = pd.to_numeric(df_units["GenerationUnitInstalledCapacity[MW]"],errors="coerce")

# Keep records with the required fields
df_units = df_units.dropna(subset=["GenerationUnitCode","ValidityPeriodStart(UTC)","GenerationUnitInstalledCapacity[MW]"])

##############################################################################################################################################

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

# Keep only units that have valid start and end timestamps
df_units_fill = df_units_fill.dropna(
    subset=["ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)"]
).copy()

start_date = df_pivot["DateTime"].min()
end_date = df_pivot["DateTime"].max()

# Keep units whose validity periods overlap the required date range
df_units_fill = df_units_fill[
    (df_units_fill["ValidityPeriodStart(UTC)"] <= end_date)
    & (df_units_fill["ValidityPeriodEnd(UTC)"] >= start_date)
].copy()

# Generate hourly timestamps for each unit
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

print("Hourly capacity shape:", df_pivot_filled.shape)
print("Missing values filled:", filled_cells)
print("Remaining missing asset-hour values:",
      df_pivot_filled.drop(columns="DateTime").isna().sum().sum())

# Confirm the original pivot was not modified
print("Original shape:", df_pivot.shape)
print("Filled shape:", df_pivot_filled.shape)

# Check a few rows
print(df_pivot_filled.iloc[:5, :8])

# Save the result
df_pivot_filled.to_csv(
    "v1_hourly_capacity_filled.csv",
    index=False
)
print("========&&&&&&& Installed capacity Filled hourly data saved to v1_hourly_capacity_filled.csv &&&&&&=======")


# Diagnosis
print("\n========= ************************ Diagnosis ******************** =========")
# Count missing values for each asset
missing_by_asset = df_pivot_filled.drop(
    columns="DateTime"
).isna().sum()

missing_by_asset = missing_by_asset[missing_by_asset > 0].sort_values(
    ascending=False
)

print("Assets with remaining missing values:", len(missing_by_asset))
print("\nTop 20 assets with missing values:")
print(missing_by_asset.head(20))

print("\nTotal missing values:", missing_by_asset.sum())

# Assets with missing hourly values
missing_assets = set(missing_by_asset.index)

# Assets present in the installed-capacity mapping
mapped_assets = set(df_units_hourly["GenerationUnitCode"].unique())

print("Assets with missing values:", len(missing_assets))
print("Missing-value assets with mapping:", len(missing_assets & mapped_assets))
print("Missing-value assets without mapping:", len(missing_assets - mapped_assets))

print("\nExamples without mapping:")
print(list(missing_assets - mapped_assets)[:10])


# # Inspect assets that still have missing hourly capacity
# missing_assets = (
#     df_pivot_filled.drop(columns="DateTime")
#     .isna()
#     .sum()
#     .loc[lambda s: s > 0]
#     .index
# )

# mapping_summary = (
#     df_units_fill[
#         [
#             "GenerationUnitCode",
#             "GenerationUnitStatus",
#             "ValidityPeriodStart(UTC)",
#             "ValidityPeriodEnd(UTC)",
#             "GenerationUnitInstalledCapacity[MW]"
#         ]
#     ]
#     .drop_duplicates()
# )

# mapping_summary = mapping_summary[
#     mapping_summary["GenerationUnitCode"].isin(missing_assets)
# ]

# print(
#     mapping_summary.sort_values(
#         ["GenerationUnitCode", "ValidityPeriodStart(UTC)"]
#     ).to_string(index=False)
# )



# asset = "15W-BHALPV--AE-8"

# # 1. Show all validity records for this asset
# print("VALIDITY RECORDS")
# print(
#     df_units_fill.loc[
#         df_units_fill["GenerationUnitCode"].eq(asset),
#         [
#             "GenerationUnitStatus",
#             "ValidityPeriodStart(UTC)",
#             "ValidityPeriodEnd(UTC)",
#             "GenerationUnitInstalledCapacity[MW]"
#         ]
#     ].sort_values("ValidityPeriodStart(UTC)").to_string(index=False)
# )

# # 2. Count missing hours by month
# missing_hours = (
#     df_pivot_filled.loc[
#         df_pivot_filled[asset].isna(), "DateTime"
#     ]
#     .dt.month
#     .value_counts()
#     .sort_index()
# )

# print("\nMISSING HOURS BY MONTH")
# print(missing_hours)

# asset = "15W-BHALPV--AE-8"

# print(
#     df_pivot.loc[
#         df_pivot["DateTime"].dt.month.eq(1),
#         ["DateTime", asset]
#     ].head(24).to_string(index=False)
# )