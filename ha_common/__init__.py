"""Shared helpers for the Cost-of-Living-Tracker updater scripts.

Named `ha_common` (not `common`) to avoid a hard import collision with the
`common` package shipped inside the `census-common` distribution, which the
`census-forecaster` dependency installs into site-packages.
"""
