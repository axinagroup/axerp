# Bugfix Requirements Document

## Introduction

This document addresses the AXERP installation failure caused by a module name mismatch between the modules.txt configuration and the actual module folder name, AND prevents this bug from recurring on future upstream syncs.

**Root Cause:** The `scripts/smart_rename.py` script performed a global find-and-replace of "ERPNext" → "AXERP" across all files, which inadvertently changed "ERPNext Integrations" to "AXERP Integrations" in `modules.txt`. However, the script did NOT rename the actual folder from `erpnext_integrations/` to `axerp_integrations/`, nor did it update the hundreds of Python import statements throughout the codebase that reference `erpnext.erpnext_integrations.*`.

This incomplete rebranding resulted in Frappe being unable to locate the module during app installation, causing a ModuleNotFoundError.

**Impact:** The bug prevents successful installation of the AXERP app on any site, blocking deployment and updates. Additionally, since `scripts/smart_rename.py` runs during every upstream sync (see `scripts/sync_upstream.sh`), this bug will recur on the next upstream merge unless the script is fixed.

**Correct Fix:** This bugfix has TWO components:

1. **Immediate Fix:** Revert the module name in `modules.txt` from "AXERP Integrations" back to "ERPNext Integrations" to match the actual folder name (`erpnext_integrations/`) and all existing code references.

2. **Prevent Recurrence:** Update `scripts/smart_rename.py` to exclude the integrations module from rebranding. The script must preserve "ERPNext Integrations" in modules.txt, JSON module fields, the `erpnext_integrations/` folder name, and imports like `erpnext.erpnext_integrations.*` while continuing to rebrand everything else to "AXERP".

## Bug Analysis

### Current Behavior (Defect)

**Immediate Bug - Module Name Mismatch:**

1.1 WHEN running `bench --site [site-name] install-app erpnext` THEN the system raises ModuleNotFoundError: No module named 'erpnext.axerp_integrations'

1.2 WHEN Frappe attempts to import the module listed as "AXERP Integrations" in modules.txt THEN the system fails because it looks for folder `axerp_integrations/` but finds `erpnext_integrations/`

1.3 WHEN the module name in modules.txt does not match the actual folder name THEN the system cannot complete the app installation process

**Root Cause - Script Damages Integrations Module:**

1.4 WHEN `scripts/smart_rename.py` runs during upstream sync THEN the script renames "ERPNext Integrations" to "AXERP Integrations" in modules.txt

1.5 WHEN `scripts/smart_rename.py` processes files THEN the script does NOT exclude the integrations module from rebranding, causing the mismatch to recur

1.6 WHEN `scripts/sync_upstream.sh` executes THEN the script calls `smart_rename.py`, which re-introduces the bug on every upstream merge

### Expected Behavior (Correct)

**Immediate Fix - Restore Module Name:**

2.1 WHEN running `bench --site [site-name] install-app erpnext` THEN the system SHALL complete the installation successfully without module import errors

2.2 WHEN Frappe attempts to import the module listed in modules.txt THEN the system SHALL successfully locate and import the module because the module name "ERPNext Integrations" matches the actual folder name `erpnext_integrations/`

2.3 WHEN the module name in modules.txt is "ERPNext Integrations" THEN the system SHALL find the corresponding folder named `erpnext_integrations/` and all existing import statements SHALL continue to work

**Script Fix - Prevent Future Damage:**

2.4 WHEN `scripts/smart_rename.py` runs during upstream sync THEN the script SHALL preserve "ERPNext Integrations" in modules.txt without renaming it to "AXERP Integrations"

2.5 WHEN `scripts/smart_rename.py` processes JSON files with module fields THEN the script SHALL NOT rename "ERPNext Integrations" to "AXERP Integrations"

2.6 WHEN `scripts/smart_rename.py` processes Python import statements THEN the script SHALL preserve imports like `erpnext.erpnext_integrations.*` without modification

2.7 WHEN `scripts/smart_rename.py` processes folder names THEN the script SHALL NOT attempt to rename the `erpnext_integrations/` folder

2.8 WHEN `scripts/sync_upstream.sh` executes and calls `smart_rename.py` THEN the integrations module SHALL remain intact with "ERPNext Integrations" branding

### Unchanged Behavior (Regression Prevention)

**Module Installation and Functionality:**

3.1 WHEN installing AXERP with all other modules (Accounts, CRM, Buying, etc.) THEN the system SHALL CONTINUE TO install those modules successfully

3.2 WHEN existing Python code imports from `erpnext.erpnext_integrations.*` (as found in hooks.py, patches, utils, etc.) THEN the system SHALL CONTINUE TO resolve those imports correctly

3.3 WHEN existing doctypes, pages, or code reference the integrations module THEN the system SHALL CONTINUE TO resolve those references correctly

3.4 WHEN the integrations module is used within the application THEN the system SHALL CONTINUE TO function correctly with all existing integrations and features

3.5 WHEN upgrading or migrating existing sites THEN the system SHALL CONTINUE TO maintain data integrity and module functionality

**Script Rebranding Functionality:**

3.6 WHEN `scripts/smart_rename.py` processes files THEN the script SHALL CONTINUE TO rename "ERPNext" to "AXERP" for all other modules and content (excluding the integrations module)

3.7 WHEN `scripts/smart_rename.py` processes modules.txt THEN the script SHALL CONTINUE TO rename other module names like "ERPNext Assets" to "AXERP Assets"

3.8 WHEN `scripts/smart_rename.py` processes JSON files THEN the script SHALL CONTINUE TO rebrand module fields for all modules except "ERPNext Integrations"

3.9 WHEN `scripts/sync_upstream.sh` executes THEN the script SHALL CONTINUE TO perform all other upstream sync operations correctly
