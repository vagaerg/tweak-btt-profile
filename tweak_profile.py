#!/usr/bin/env python3.9

"""
This modifies the amazing AquaTouch BTT touchbar profile to match my personal preferences
Did this as a script so that I don't need to re-do this every time AquaTouch is updated
"""

import json
import base64
from functools import partial
import os
import plistlib
import uuid
import zipfile
import sys
import copy
from collections import namedtuple
from typing import Dict, List, Any, Sequence, Callable, Union, Optional


AppInfo = namedtuple("AppInfo", ["bundle_name", "app_name"])
JSON_CFG_FILENAME = "presetjson.bttpreset"
TRIGGER_TYPES_TO_DELETE = {653}
TRIGGER_APPS_TO_DELETE = {"Media Key Shortcuts"}
APPS_TO_CLONE = {
    AppInfo("com.microsoft.VSCode", "Visual Studio Code"): [
        AppInfo("com.microsoft.VSCodeInsiders", "Visual Studio Code - Insiders"),
        AppInfo("com.microsoft.VSCodeExploration", "Visual Studio Code - Exploration"),
    ]
}


def load_cfg_file(zipfile: zipfile.ZipFile, path: str) -> Dict[str, Any]:
    return json.loads(zipfile.read(path))


def compute_new_uid(
    copy_from: int,
    copy_to: int,
    item_count: int,
    uid_value: int,
) -> int:
    if uid_value < copy_from or uid_value > copy_to:
        # ref to something else
        return uid_value
    return item_count + (uid_value - copy_from)


def recursive_modify_collection(v: Union[Dict, List], modify_callable: Callable) -> None:
    if isinstance(v, dict):
        for key, value in v.items():
            if isinstance(value, dict):
                recursive_modify_collection(value, modify_callable)
                continue
            if isinstance(value, list):
                recursive_modify_collection(value, modify_callable)
                continue
            new_value = modify_callable(key, value)
            if new_value is not None:
                v[key] = new_value
    elif isinstance(v, list):
        for item_pos, item in enumerate(v):
            if isinstance(item, (list, dict)):
                recursive_modify_collection(item, modify_callable)
            else:
                new_value = modify_callable(None, item)
                if new_value:
                    v[item_pos] = new_value
    else:
        print(f"Ignoring item of type {type(v)}")


def clone_app(source_app: Dict[str, Any], target_app: AppInfo) -> Dict[str, Any]:
    def fix_uuid(key: str, value: str) -> str:
        if key != "BTTUUID":
            return None

        if not isinstance(value, str):
            raise ValueError(f"Key BTTUUID should be of type str, found {type(value)}")
        return str(uuid.uuid4()).upper().strip()

    new_app = copy.deepcopy(source_app)
    new_app["BTTAppName"] = target_app.app_name
    new_app["BTTAppBundleIdentifier"] = target_app.bundle_name
    # Regenerate UUIDs
    recursive_modify_collection(new_app, fix_uuid)
    return new_app


def add_supported_app(
    app_config: Dict[str, Any],
    source_app: AppInfo,
    target_apps: Sequence[AppInfo],
) -> None:
    def fix_uuids(
        copy_from: int,
        copy_to: int,
        previous_length: int,
        key: Any,
        value: Any,
    ) -> plistlib.UID:
        if isinstance(value, plistlib.UID):
            value.data = compute_new_uid(
                copy_from,
                copy_to,
                previous_length,
                value.data
            )
        return None

    activation_group_cond = app_config["BTTActivationGroupCondition"]
    # Condition is a base64-encoded binary plist
    parsed_plist = plistlib.loads(base64.urlsafe_b64decode(activation_group_cond))
    # Note to future self: I have no clue how plist's work - just what I gathered
    # from reading and reversing the existing file
    #
    # figure out the right operators

    try:
        center = parsed_plist["$objects"].index(source_app.bundle_name)
        use_bundle = True
    except:
        center = parsed_plist["$objects"].index(source_app.app_name)
        use_bundle = False

    # start searching back from the located bundle / app name
    # keep track of any index with a forward ref to our bundle/app name
    # or a forward ref to another item that has one to it (transitive)
    idxs_to_search = [center]
    for i in range(center, 0, -1):
        obj_at_pos = parsed_plist["$objects"][i]
        if not isinstance(obj_at_pos, dict):
            continue
        for k, v in obj_at_pos.items():
            # if the curre
            if isinstance(v, plistlib.UID):
                if v.data in idxs_to_search:
                    # Keep track of the new forward ref
                    idxs_to_search.append(i)
    copy_from = idxs_to_search[-1]

    # The first item in our predicate will have forward refs to all the required bits
    # including the predicate
    # transitively search for it
    copy_to = max(
        (
            v.data
            for k, v in parsed_plist["$objects"][copy_from].items()
            if isinstance(v, plistlib.UID)
        )
    )
    # search for potential forward refs from copy_to onwards
    while True:
        if not isinstance(parsed_plist["$objects"][copy_to], dict):
            break
        new_max = max(
            (
                v.data
                for k, v in parsed_plist["$objects"][copy_to].items()
                if isinstance(v, plistlib.UID)
            )
        )
        if new_max <= copy_to:
            break
        copy_to = new_max

    root_levels_to_add = []
    for target_app in target_apps:
        new_items = copy.deepcopy(parsed_plist["$objects"][copy_from:(copy_to + 1)])
        previous_length = len(parsed_plist["$objects"])
        print(f"Adding {target_app} - starting at ID {previous_length}")
        root_levels_to_add.append(previous_length)
        fix_callable = partial(fix_uuids, copy_from, copy_to, previous_length)
        for item_pos, item in enumerate(new_items):
            if isinstance(item, plistlib.UID):
                fix_callable(None, item)
            elif isinstance(item, (list, dict)):
                recursive_modify_collection(item, fix_callable)
            elif isinstance(item, str):
                if use_bundle and item == source_app.bundle_name:
                    new_items[item_pos] = target_app.bundle_name
                elif not use_bundle and item == source_app.app_name:
                    new_items[item_pos] = target_app.app_name
        parsed_plist["$objects"].extend(new_items)

    # find top level pointer to all the apps
    for item_pos, item in enumerate(parsed_plist["$objects"]):
        if not isinstance(item, dict):
            continue
        if "NS.objects" not in item:
            continue
        # search for our minimum range - i.e. the first item that denoted the app entry we copied
        if plistlib.UID(copy_from) in item["NS.objects"]:
            for new_root in root_levels_to_add:
                item["NS.objects"].append(plistlib.UID(new_root))
            break
    else:
        raise ValueError("Could not append new app - could not locate root level list")

    print("Added to root tree - dumping plist and we'll be done")
    app_config["BTTActivationGroupCondition"] = base64.standard_b64encode(
        plistlib.dumps(
            parsed_plist, fmt=plistlib.FMT_BINARY, sort_keys=True,
        )
    ).decode("ascii")


def remove_touchbar_ctx(loaded_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if "BTTPresetContent" not in loaded_cfg:
        raise ValueError("BTTPresetContent not preset at the root level - invalid preset spec")

    found_apps = {
        source_app: False
        for source_app in APPS_TO_CLONE
    }
    for app_pos, app_config in enumerate(loaded_cfg["BTTPresetContent"]):
        # Delete the touchbar button that overrides the global music player
        app_name = app_config["BTTAppName"]
        print(f"Checking {app_name}...")
        for app_to_delete in TRIGGER_APPS_TO_DELETE:
            if app_to_delete in app_name:
                print("Deleting it...")
                del loaded_cfg["BTTPresetContent"][app_pos]
                continue

        for trigger_pos, trigger in enumerate(app_config.get("BTTTriggers", [])):
            if trigger.get("BTTTriggerType") in TRIGGER_TYPES_TO_DELETE:
                print(f"Found trigger to delete at pos {trigger_pos}")
                del app_config["BTTTriggers"][trigger_pos]

        # Copy apps
        app_key = AppInfo(app_config.get("BTTAppBundleIdentifier"), app_name)
        if app_key in APPS_TO_CLONE:
            found_apps[app_key] = True
            for target_app in APPS_TO_CLONE[app_key]:
                new_app = clone_app(app_config, target_app)
                loaded_cfg["BTTPresetContent"].append(new_app)

        # Check if activation group
        if (
            "BTTActivationGroupName" in app_config
            and "BTTActivationGroupCondition" in app_config
        ):
            if "UNSUPPORTED APP" in app_name.upper():
                for source_app, target_apps in APPS_TO_CLONE.items():
                    add_supported_app(app_config, source_app, target_apps)

    for source_app, was_found in found_apps.items():
        if was_found:
            print(f"Config could be copied successfully for {source_app}")
        else:
            raise RuntimeError(f"Failed to find source config for {source_app}")
    return loaded_cfg


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} source-file (bttpreset ext)")
    input_zipfile = zipfile.ZipFile(sys.argv[1], mode="r")
    loaded_cfg_file = load_cfg_file(input_zipfile, JSON_CFG_FILENAME)
    modified_cfg_file = remove_touchbar_ctx(loaded_cfg_file)

    current_fname, current_ext = os.path.splitext(sys.argv[1])
    new_path = f"{current_fname}_new{current_ext}"
    new_zipfile = zipfile.ZipFile(new_path, "w")
    for item in input_zipfile.infolist():
        buffer = input_zipfile.read(item.filename)
        if (item.filename != JSON_CFG_FILENAME):
            new_zipfile.writestr(item, buffer)
        else:
            new_zipfile.writestr(JSON_CFG_FILENAME, json.dumps(modified_cfg_file))
