# Installed-Product Docker Workflow

The authoritative current workflow is [DEV.md](../DEV.md).
Use `sh docker/e2e.sh build`, followed by installed `papersmith` commands.
No checkout mount, `PYTHONPATH`, root scripts or repository agent files are used.

The older live-source/domain runner was replaced by issue #71. Stopped runs and
volumes are preserved; their evidence is historical, not generic product acceptance.
