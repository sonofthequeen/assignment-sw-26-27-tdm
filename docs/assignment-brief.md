# Original assignment brief (Race UP)

> This is the official Race UP Electric Software 2026/27 selection brief for Task 2, preserved
> verbatim from the original repository README. It is organiser content, not project
> documentation. The project README is [../README.md](../README.md).

---

# Task 2 — Test Data Manager

## 1. Introduction
The **Test Data Manager (TDM)** is an application for collecting, organizing, visualizing and querying data generated during Formula Student testing activities.

You are given below a description of the functionalities and the type of data that is required to be stored and queried. You are expected to identify the actual domain model and build a small functional application for it.

---
# 2. The interview
We are looking to procure a new, centralized Test Data Management (TDM) system to replace our current workflow, which relies on heavily distributed and manually maintained spreadsheets. We need an engineering-grade historical database that allows our team to seamlessly retrieve and correlate testing data across seasons, vehicles, drivers, tracks, and physical measurements.

**Core Data Hierarchy and Season Management** The foundational hierarchy of the system must map data from the **Season** down to the **Test**, then to the **Run**, and finally to the individual **Lap**. The system must inherently support multiple seasons and multiple vehicle generations; it cannot be hard-coded to a single car or year.

At the highest level, the system needs to digitize our yearly testing objectives (detailing what needs testing, priorities, and desired repetitions) and link them directly to the specific tests and runs where they are addressed. A "Test" must serve as a central hub for context, capturing the date, vehicle, track location, relevant objectives, status, problems encountered, and overall engineering conclusions.

**Planning vs. Actual Execution** A critical dependency in our workflow is the relationship between the _Planned Run Plan_ and the _Actual Test Execution_. Before a test, we map out expected runs, including target times, expected lap counts, battery charge/fuel limits, designated drivers, and expected vehicle control maps. During the test day, reality often deviates. The system must preserve both the plan and the actual execution, allowing us to easily determine which planned runs were modified or cancelled, which unexpected runs were added, and any discrepancies in driver, timing, or setup.

**The "Run" and the Setup Story** The "Run" is the fundamental execution entity. It must capture track and environmental conditions (ambient/asphalt temperatures), driver assignments, and expected vs. completed laps.

Crucially, the system must allow engineers to reconstruct the complete **Setup Story** of the vehicle across these runs. For any run, we need to know exactly what setup was used, what changed compared to the previous run, when it changed, and why. This encompasses detailed suspension data (springs, dampers, ARB), static camber, toe settings, corner weights, shims, and control configurations (power limits, torque vectoring, RPM). We do not want a flat, excessively wide database table; the architecture must intelligently handle setup snapshots, parameter tracking, reusable configurations, and differentiate between whole-vehicle properties and individual corner (FL, FR, RL, RR) properties.

**Tires, Measurements, and Alignment** Tire management is highly dependent on run data. The system must track tire compounds and individual physical tire sets, allowing us to query historical runs based on the tires used. Furthermore, we require strict tracking of pre- and post-run measurements. This includes capturing tire temperatures across three zones (outer, center, inner) and pressures for all four corners. We also need to log physical vehicle alignment measurements (camber and toe) per corner. These measurements must be inextricably linked to their corresponding runs and setups to allow for accurate lap-time correlation.

**Laps, Mileage, and Tracks** Lap-time data must be stored at the individual lap level, capturing raw times, penalties, and automatically deriving the best lap for a given run without manual synchronization.

To support this, Track Locations and specific Track Layouts must be modelled as reusable entities containing verified track lengths and activity types (e.g., Skidpad, Endurance, Autocross). By combining these track lengths with lap data, the system must automatically calculate and track **Vehicle and Driver Mileage**. We expect the system to provide automated, cumulative distance totals per run, per test, per season, and for the entire lifespan of the vehicle or driver, completely eliminating manual mileage tallying.

**Telemetry, Logs, and Test-Day Logistics** While the TDM does not need to be a high-frequency time-series telemetry analyzer, it must act as our central index for telemetry and log files. The system must associate data files with their specific tests and runs, tracking file types, metadata, and storage locations to guarantee traceability. Additionally, the system should feature a reusable model for our test-day "Postazioni" (stations), allowing us to assign personnel and roles (e.g., telemetry desk, pit wall) to physical test locations.

**Technical, Querying, and Delivery Requirements** This must be built as a robust engineering system, not a simple CRUD application. We expect strict data integrity (foreign keys, validation to prevent impossible lap/distance values, prevention of duplicate tire IDs) and clearly defined, strictly documented engineering units (metric/SI) across the database.

The paramount reason for procuring this system is **Historical Querying**. Our engineers must be able to intuitively execute complex, multi-filter cross-test queries (e.g., "Show all runs from the current season by Driver X, on Tire Compound Y, within an asphalt temperature range of 30°C–40°C").

For the final delivery, we require:
1. A fully functional backend API and a usable frontend interface to manage and visualize this data.
2. Comprehensive documentation covering the system architecture and database design (ER/UML diagrams).
3. A documented data-import strategy with an implemented tool to migrate our existing, messy historical spreadsheet data.
4. A highly reproducible setup process (e.g., containerized, using automated database migrations) populated with realistic seed data that demonstrates the system's full capabilities out-of-the-box.
5. Automated testing covering core mileage calculations, historical queries, and database constraints.

---
# 3. The objective
Build a structured historical representation of the team's testing process that engineers can reliably use, query, compare and extend over multiple tests, vehicles and seasons.

Given that this is a large task, do as much as you can and don't worry if you are unable to model everything or have a complete functional application: we put focus on the design choices and the thoughts that were behind them.
