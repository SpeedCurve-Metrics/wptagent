# Notes

Agent copies these preferences and policies into the appropriate Chrome directories

## Preferences

Available preferences listed at the bottom of https://niek.github.io/chrome-features/

Stored in {profile_dir}/Default/Preferences

A unique profile directory is created fresh for each WPT run and specified via `--user-data-dir=`

## Policies

Chrome Enterprise policies: https://chromeenterprise.google/policies

Stored in /etc/opt/chrome/policies/managed 

Can check currently set policies via chrome://policy

