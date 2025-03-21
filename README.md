# 🚀 QTempo

## 📌 Overview

QTempo is a **QGIS Python plugin** designed to simplify the integration of **statistical and geospatial data**. It provides an intuitive **graphical user interface (GUI)** for querying the **TEMPO-Online** database, managed by the **National Institute of Statistics**, and seamlessly adds the retrieved datasets as layers in **QGIS**. By streamlining this process, QTempo significantly enhances **geospatial analysis** and the **visualization of socio-economic indicators**.

## ✨ Features

- 🔍 **Query the TEMPO-Online database** via a user-friendly interface.
- 🌍 **Retrieve and visualize administrative boundaries** from:
  - 🏢 **National Agency for Cadaster and Land Registration (ANCPI)** (via ArcGIS Map Service, POST request).
  - 🌐 **Geographical Information System of the Commission (GISCO)** (via GISCO API, GET request).
- 🔗 **Join statistical data with administrative boundaries** at the commune level.
- ⚡ **Seamless integration with QGIS**, using built-in PyQGIS objects without external dependencies.
- 📥 **Available in the QGIS Python Plugin Repository** for easy installation and updates.

## 🔧 Installation

### 📦 From the QGIS Plugin Manager:

1. 🖥️ Open **QGIS**.
2. 🛠️ Navigate to **Plugins > Manage and Install Plugins**.
3. 🔎 Search for **QTempo**.
4. ✅ Click **Install Plugin**.

### 🏗️ Manual Installation:

1. 📥 Download the latest version from the [QGIS Plugin Repository](https://plugins.qgis.org/plugins/).
2. 📂 Extract the plugin folder and place it in your QGIS plugins directory:
   - 🖥️ **Windows**: `C:\Users\YourUsername\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - 🐧 **Linux/Mac**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
3. 🔄 Restart QGIS and enable the plugin from **Plugins > Manage and Install Plugins**.

## 🚀 Usage

1. 🖥️ Open **QGIS** and activate **QTempo** from the Plugins menu.
2. 📂 Select the preferred dataset.
3. 🔍 Select the query options and request the data.
4. 🗂️ Add the retrieved table as a layer in QGIS.

### (OPTIONAL) If the data is at commune level:
5. 🌍 Select the preferred **administrative boundary dataset** (ANCPI or GISCO).
6. 🔄 Pivot the table using the grouping options.
7. 🗺️ Press on **"Add vector layer"** to add the layer to your QGIS project!

Examples can be found at the following playlist [https://www.youtube.com/playlist?list=PLwnLbfcxh3V3g5dXJ1FlzdRsYwn7bYPls](https://youtube.com/playlist?list=PLwnLbfcxh3V3g5dXJ1FlzdRsYwn7bYPls&si=0UfuR-gy2kFRUAOB)

## 🛠️ Dependencies

QTempo is built entirely using **PyQGIS** and does not require additional Python libraries.

## 🤝 Support & Contributions

For feature requests, bug reports, or contributions, please visit the [GitHub repository](https://github.com/alecsandrei/QTempo/issues) and submit an **issue** or **pull request**.

## 📜 License

QTempo is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.


# Disclaimer
This plugin, QTempo, is an independent project created by Cuvuliuc Alex-Andrei. It is not an official product of the National Institute of Statistics, and Cuvuliuc Alex-Andrei is not affiliated, associated, authorized, endorsed by, or in any way officially connected with National Institute of Statistics or any of its subsidiaries or its affiliates.

# References

[Necula, M., Țîru, A. M., & Oancea, B. (2019). Tempo – an R package to access the TEMPO-Online database. The Journal of National Institute of Statistics, Romanian Statistical Review(3). https://www.revistadestatistica.ro/2019/09/tempo-an-r-package-to-access-the-tempo-online-database/](https://github.com/MarianNecula/TEMPO)

[Vereș, M. (2025). Mark-veres/tempo.py [Python]. https://github.com/mark-veres/tempo.py (Original work published 2024)
](https://github.com/mark-veres/tempo.py)
