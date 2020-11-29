This does two things:
- Removes the AquaTouch icon from the control strip (so that the music one can show), in any app
- Copies the configuration from vscode to vscode insiders and exploration (ARM build); can be tweaked to copy anything else
- Removes the media shortcut keys (they interfere with iTerm, pgup, pgdown): disabling them is not enough as BTT seems to register the shortcut anyway

This was mostly a fun exercise to figure out what the profile files look like.

## How to run:

`./tweak_profile.py [bttprofilezip file]`


## How to fix the gesture bar popping up after Cmd+Tab

- Disable the blue emoji item under "Unsupported apps": "Active touch group"
