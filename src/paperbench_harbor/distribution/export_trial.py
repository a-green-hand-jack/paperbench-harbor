"""Compatibility entry point for the sanitized trial exporter."""



from paperbench_harbor.trials.export import TrialExportConfig, TrialExportError, export_trial, main

__all__ = ["TrialExportConfig", "TrialExportError", "export_trial"]


if __name__ == "__main__":
    main()
