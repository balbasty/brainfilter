SUFFIXES = {
    "anat": [
        # Nonparametric
        "FLAIR",
        "PDT2",
        "PDw",
        "T1w",
        "T2starw",
        "T2w",
        "angio",
        "inplaneT1",
        "inplaneT2",
        # Parametric
        "Chimap",
        "M0map",
        "MTRmap",
        "MTVmap",
        "MTsat",
        "MWFmap",
        "PDmap"
        "R1map",
        "R2map",
        "R2starmap",
        "RB1map",
        "S0map",
        "T1map",
        "T1rho",
        "T2map",
        "T2starmap",
        "TB1map",
        # Other
        "defacemask",
        # Deprecated
        "FLASH",
        "PD",
        "T2star",
        # Collections
        "MEGRE",
        "MESE",
        "VFA",
        "IRT1",
        "MP2RAGE",
        "MPM",
        "MTS",
        "MTR",
    ],
    "func": [
        # fMRI
        "bold",
        "cbv",
        "sbref",
        "noRF",
        "phase",
        # Metadata
        "events",
        "physio",
        "stim",
    ],
    "dwi": [
        "dwi",
        "sbref",
        # Scanner-derivatives
        "ADC",
        "FA",
        "S0map",
        "colFA",
        "expADC",
        "trace",
        # Metadata
        "physio",
        "stim",
    ],
    "perf": [
        "asl",
        "m0scan",
        "noRF",
        # Metadata
        "aslcontext",
        "asllabeling",
        "physio",
        "stim",
    ],
    "fmap": [
        # B0 field maps
        "epi",
        "fieldmap",
        "magnitude",
        "magnitude1",
        "magnitude2",
        "phase1",
        "phase2",
        "phasediff",
        # TB1 maps
        "TB1AFI",
        "TB1DAM",
        "TB1EPI",
        "TB1RFM",
        "TB1SRGE",
        "TB1TFL",
        "TB1map",
        # RB1 maps
        "RB1COR",
        "RB1map",
    ],
    "meg": [
        "meg",
        # Metadata
        "events",
        "physio",
        "stim",
        "channels",
        "coordsystem",
        "markers",
        "photo",
        "headshape",
    ],
    "eeg": [
        "eeg",
        # Metadata
        "events",
        "physio",
        "stim",
        "channels",
        "electrodes",
        "coordsystem",
        "photo",
    ],
    "ieeg": [
        "ieeg",
        # Metadata
        "events",
        "physio",
        "stim",
        "channels",
        "electrodes",
        "coordsystem",
        "photo",
    ],
    "beh": [
        "beh",
        # Metadata
        "events",
        "physio",
        "stim",
    ],
    "pet": [
        "pet",
        "blood",
        # Metadata
        "events",
        "physio",
        "stim",
    ],
    "micr": [
        "2PE",
        "BF",
        "CARS",
        "CONF",
        "DIC",
        "DF",
        "FLUO",
        "MPE",
        "NLO",
        "OCT",
        "PC",
        "PLI",
        "SEM",
        "SPIM",
        "SR",
        "TEM",
        "XPCT",
        "uCT",
        "photo"
    ],
    "nirs": [
        "nirs",
        # Metadata
        "events",
        "physio",
        "stim",
        "channels",
        "optodes",
        "coordsystem",
    ],
    "motion": [
        "motion",
        # Metadata
        "events",
        "physio",
        "stim",
        "channels",
    ],
    "mrs": [
        "mrsi",
        "mrsref",
        "svs",
        "unloc",
        # Metadata
        "events",
    ]
}
