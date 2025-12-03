# stdlib
from numbers import Number as number
from re import compile as _p    # -> re.Pattern
from typing import Annotated, Literal, T

# internals
from brainfilter.re import (
    bids_label, bids_index,
    ext_json, ext_nii, ext_tsv, ext_tsvgz, ext_bval, ext_bvec
)
from brainfilter.schemas.utils import (
    URI, Positive, Directory, File,
    BvalFile, BvecFile, NiftiFile, JSONFile, TSVFile, TSVGZFile
)
from brainfilter.validation import (
    DirectorySchema, JSONSchema, JSONFileValidator, Required, TSVFileValidator,
    Recommended, Optional, Deprecated,
    # RequiredIf, RecommendedIf
)
from brainfilter.validator_zoo import Maximum, Minimum
from brainfilter.versioning import VersionSpecifier

# ======================================================================
#                         J S O N   S C H E M A S
# ======================================================================

ScannerHardwareSchema = JSONSchema({
    "Manufacturer": Annotated[
        str,
        Recommended,
    ],
    "ManufacturersModelName": Annotated[
        str,
        Recommended,
    ],
    "DeviceSerialNumber": Annotated[
        str,
        Recommended,
    ],
    "StationName": Annotated[
        str,
        Recommended,
    ],
    "SoftwareVersions": Annotated[
        str,
        Recommended,
    ],
    "HardcopyDeviceSoftwareVersion": Annotated[
        str,
        Deprecated,
    ],
    "MagneticFieldStrength": Annotated[
        number,
        Recommended,
        # RequiredIf["Is under perf/"],
    ],
    "ReceiveCoilName": Annotated[
        str,
        Recommended,
    ],
    "ReceiveCoilActiveElements": Annotated[
        str,
        Recommended,
    ],
    "NumberReceiveCoilActiveElements": Annotated[
        int,
        Optional,
    ],
    "GradientSetType": Annotated[
        str,
        Optional,
    ],
    "MRTransmitCoilSequence": Annotated[
        str,
        Optional,
    ],
    "MatrixCoilMode": Annotated[
        str,
        Recommended,
    ],
    "CoilCombinationMethod": Annotated[
        str,
        Recommended,
    ],
    "NumberTransmitCoilActiveElements": Annotated[
        int,
        Optional,
    ],
    "TablePosition": Annotated[
        tuple[number, number, number],
        Optional,
        # RecommendedIf["has chunk-*"],
    ],
})

InstitutionInformationSchema = JSONSchema({
    "InstitutionName": Annotated[
        str,
        Recommended,
    ],
    "InstitutionAddress": Annotated[
        str,
        Recommended,
    ],
    "InstitutionalDepartmentName": Annotated[
        str,
        Recommended,
    ],
})

SequenceSpecificsSchema = JSONSchema({
    "PulseSequenceType": Annotated[
        str,
        Recommended,
    ],
    "ScanningSequence": Annotated[
        str | list[str],
        Recommended,
    ],
    "SequenceVariant": Annotated[
        str | list[str],
        Recommended,
    ],
    "ScanOptions": Annotated[
        str | list[str],
        Optional,
    ],
    "SequenceName": Annotated[
        str,
        Recommended,
    ],
    "PulseSequenceDetails": Annotated[
        str,
        Recommended,
    ],
    "NonlinearGradientCorrection": Annotated[
        bool,
        Optional,
        # RecommendedIf["has associated pet data"],
    ],
    "MRAcquisitionType": Annotated[
        str,
        Literal["1D, 2D, 3D"],
        Recommended,
        # RequiredIf["is under perf/"],
    ],
    "MTState": Annotated[
        bool,
        Optional,
        # RequiredIf["has mt-*"],
    ],
    "MTOffsetFrequency": Annotated[
        number,
        Optional,
    ],
    "MTPulseBandwidth": Annotated[
        number,
        Optional,
    ],
    "MTNumberOfPulses": Annotated[
        int,
        Optional,
    ],
    "MTPulseShape": Annotated[
        str,
        Literal[
            "HARD",
            "GAUSSIAN",
            "GAUSSHANN",
            "SINC",
            "SINCHANN",
            "SINCGAUSS",
            "FERMI",
        ],
        Optional,
    ],
    "MTPulseDuration": Annotated[
        number,
        Optional,
    ],
    "NumberShots": Annotated[
        int | tuple[int, int],
        Optional,
        # RequiredIf["is _MP2RAGE"],
    ],
    "SpoilingState": Annotated[
        bool,
        Optional,
    ],
    "SpoilingType": Annotated[
        str,
        Literal["RF", "GRADIENT", "COMBINED"],
        Optional,
    ],
    "SpoilingRFPhaseIncrement": Annotated[
        number,
        Optional,
    ],
    "SpoilingGradientMoment": Annotated[
        number,
        Optional,
    ],
    "SpoilingGradientDuration": Annotated[
        number,
        Optional,
    ],
    "WaterSuppression": Annotated[
        bool,
        Optional,
    ],
    "WaterSuppressionTechnique": Annotated[
        str,
        Optional,
    ],
    "B0ShimmingTechnique": Annotated[
        str,
        Optional,
    ],
    "B1ShimmingTechnique": Annotated[
        str,
        Optional,
    ],
})

SpatialEncodingSchema = JSONSchema({
    "ParallelReductionFactorInPlane": Annotated[
        int | number,
        Optional,
        # RecommendedIf["has ParallelAcquisitionTechnique"],
    ],
    "ParallelReductionFactorOutOfPlane": Annotated[
        int | number,
        Optional,
        # RecommendedIf["has ParallelAcquisitionTechnique"],
    ],
    "ParallelAcquisitionTechnique": Annotated[
        str,
        Optional,
    ],
    "PartialFourier": Annotated[
        number,
        Optional,
    ],
    "PartialFourierDirection": Annotated[
        str,
        Optional,
        # RecommendedIf["has PartialFourier"],
    ],
    "EffectiveEchoSpacing": Annotated[
        number,
        Optional,
        # RecommendedIf["has associated fmap data"],
    ],
    "MixingTime": Annotated[
        number,
        Optional,
        # RequiredIf["qMRI sequence needs this"],
    ],
    "PhaseEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        Recommended,
        # RequiredIf["has associated fmap data"],
    ],
    "TotalReadoutTime": Annotated[
        number,
        Recommended,
        # RequiredIf["has blip-up/down fmap"],
    ],
})

TimingSchema = JSONSchema({
    "EchoTime": Annotated[
        number | list[number],
        Recommended,
        # RequiredIf["has associated fmap or is ME-ASL"],
    ],
    "InversionTime": Annotated[
        number,
        Optional,
        # RequiredIf["has inv-*"],
    ],
    "DwellTime": Annotated[
        number,
        Recommended,
    ],
    "AcquisitionDuration": Annotated[
        Positive[number],
        Optional,
    ],
    "SliceTiming": Annotated[
        list[number],
        Recommended,
        # RequiredIf["is ASL-2D + other"],
    ],
    "SliceEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        Optional,
    ],
})

ContrastSchema = JSONSchema({
    "FlipAngle": Annotated[
        number,
        Recommended,
        # RequiredIf["LookLocker is True"]
    ],
    "NegativeContrast": Annotated[
        bool,
        Optional,
    ],
})

SliceAccelerationSchema = JSONSchema({
    "MultibandAccelerationFactor": Annotated[
        int,
        Optional,
    ],
})

AnatomicalLandmarksSchema = JSONSchema({
    "AnatomicalLandmarkCoordinates": Annotated[
        dict[str, tuple[number, number, number]],
        Recommended,
    ],
})

B0Schema = JSONSchema({
    "B0FieldIdentifier": Annotated[
        str | list[str],
        Recommended,
    ],
    "B0FieldSource": Annotated[
        str | list[str],
        Recommended,
    ],
})

TissueSchema = JSONSchema({
    "BodyPart": Annotated[
        str,
        Optional,
    ],
    "BodyPartDetails": Annotated[
        str,
        Optional,
    ],
    "BodyPartDetailsOntology": Annotated[
        URI,
        Optional,
    ],
})

DeidentificationMethodCodeSequenceSchema = JSONSchema({
    "CodeValue": Annotated[
        str,
        Recommended,
    ],
    "CodeMeaning": Annotated[
        str,
        Recommended,
    ],
    "CodingSchemeDesignator": Annotated[
        str,
        Recommended,
    ],
    "CodingSchemeVersion": Annotated[
        str,
        Recommended,
    ]
})

DeidentificationSchema = JSONSchema({
    "DeidentificationMethod": Annotated[
        list[str],
        Optional,
    ],
    "DeidentificationMethodCodeSequence": Annotated[
        list[Annotated[
            dict[str, T],
            DeidentificationMethodCodeSequenceSchema
        ]],
        Optional,
    ],
})

MRISchema = JSONSchema({
    **ScannerHardwareSchema,
    **InstitutionInformationSchema,
    **SequenceSpecificsSchema,
    **SpatialEncodingSchema,
    **TimingSchema,
    **ContrastSchema,
    **SliceAccelerationSchema,
    **AnatomicalLandmarksSchema,
    **B0Schema,
    **TissueSchema,
    **DeidentificationSchema,
})

# ======================================================================
#                           Anatomical imaging
# ======================================================================

TaskAnatSchema = JSONSchema({
    "TaskName": Annotated[
        str,
        Optional,
        # RecommendedIf["task- in filename"],
    ],
    "TaskDescription": Annotated[
        str,
        Optional,
        # RecommendedIf["task- in filename"],
    ],
    "Instructions": Annotated[
        str,
        Optional,
        # RecommendedIf["task- in filename"],
    ],
})

ExtraAnatSchema = JSONSchema({
    "ContrastBolusAgent": Annotated[
        str,
        Optional,
    ],
    "RepetitionTimeExitation": Annotated[
        Positive[number],
        Optional,
    ],
    "RepetitionTimePreparation": Annotated[
        Positive[number] | list[Positive[number]],
        Optional,
    ],
})

AnatSchema = JSONSchema({
    **MRISchema,
    **TaskAnatSchema,
    **ExtraAnatSchema,
})

# ======================================================================
#                         Functional imaging
# ======================================================================

RequiredFuncSchema = JSONSchema({
    "RepetitionTime": Annotated[
        Positive[number],
        Required,
        # MutuallyExclusive["VolumeTiming"],
    ],
    "VolumeTiming": Annotated[
        list[Positive[number]],
        Required,
        # MutuallyExclusive["RepetitionTime"],
    ],
    "TaskName": Annotated[
        str,
        Required,
    ],
})

RecommendedFuncSchema = JSONSchema({
    "NumberOfVolumesDiscardedByScanner": Annotated[
        Positive[int],
        Recommended,
    ],
    "NumberOfVolumesDiscardedByUser": Annotated[
        Positive[int],
        Recommended,
    ],
    "DelayTime": Annotated[
        Positive[number],
        Optional,
    ],
    "FrameAcquisitionDuration": Annotated[
        Positive[number],
        Optional,
        # RequiredIf["VolumeTiming but not SliceTiming"]
    ],
    "DelayAfterTrigger": Annotated[
        Positive[number],
        Optional,
    ],
    "AcquisitionDuration": Annotated[
        Positive[number],
        Deprecated,
    ],
})

TaskFuncSchema = JSONSchema({
    "Instructions": Annotated[
        str,
        Recommended,
    ],
    "TaskDescription": Annotated[
        str,
        Recommended,
    ],
    "CogAtlasID": Annotated[
        URI,
        Recommended,
    ],
    "CogPOID": Annotated[
        URI,
        Recommended,
    ],
})

FuncSchema = JSONSchema({
    **MRISchema,
    **RequiredFuncSchema,
    **RecommendedFuncSchema,
    **TaskFuncSchema
})

# ======================================================================
#                           Diffusion imaging
# ======================================================================

MultipartDWISchema = JSONSchema({
    "MultipartID": Annotated[
        str,
        Optional,
    ],
})

DWISchema = JSONSchema({
    **MRISchema,
    **MultipartDWISchema,
})

# ======================================================================
#                               ASL
# ======================================================================

CommonASLSchema = JSONSchema({
    "ArterialSpinLabelingType": Annotated[
        str,
        Literal["CASL", "PCASL", "PASL"],
        Required,
    ],
    "PostLabelingDelay": Annotated[
        Positive[number],
        Required,
    ],
    "BackgroundSuppression": Annotated[
        bool,
        Required,
    ],
    "M0Type": Annotated[
        str,
        Literal["Separate", "Included", "Estimate", "Absent"],
        Required,
    ],
    "TotalAcquiredPairs": Annotated[
        Positive[int],
        Recommended,
    ],
    "VascularCrushing": Annotated[
        bool,
        Recommended,
    ],
    "AcquisitionVoxelSize": Annotated[
        tuple[Positive[number], Positive[number], Positive[number]],
        Recommended,
    ],
    "LabelingOrientation": Annotated[
        str,
        Recommended,
    ],
    "LabelingDistance": Annotated[
        number,
        Recommended,
    ],
    "LabelingLocationDescription": Annotated[
        str,
        Recommended,
    ],
    "LookLocker": Annotated[
        bool,
        Optional,
    ],
    "LabelingEfficiency": Annotated[
        number,
        Minimum(0),
        Maximum(1),
        Optional,
    ],
    "M0Estimate": Annotated[
        Positive[number],
        Optional,
        # RequiredIf["M0Type is 'Estimate'"],
    ],
    "BackgroundSuppressionNumberPulses": Annotated[
        Positive[int],
        Optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "BackgroundSuppressionPulseTimes": Annotated[
        list[Positive[number]],
        Optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "VascularCrushingVENC": Annotated[
        Positive[number] | list[Positive[number]],
        Optional,
        # RecommendedIf["VascularCrushing is True"],
    ],
})

ExtraPCASLSchema = JSONSchema({
    "PCASLType": Annotated[
        str,
        Literal["balanced", "unbalanced"],
        Optional,
        # RecommendedIf["ArterialSpinLabelingType is 'PCASL'"],
    ],
    "CASLType": Annotated[
        str,
        Literal["single-coil", "double-coil"],
        Optional,
        # RecommendedIf["ArterialSpinLabelingType is 'CASL'"],
    ],
    "LabelingDuration": Annotated[
        Positive[number],
        Required,
    ],
    "LabelingPulseAverageGradient": Annotated[
        Positive[number],
        Recommended,
    ],
    "LabelingPulseMaximumGradient": Annotated[
        Positive[number],
        Recommended,
    ],
    "LabelingPulseAverageB1": Annotated[
        Positive[number],
        Recommended,
    ],
    "LabelingPulseDuration": Annotated[
        Positive[number],
        Recommended,
    ],
    "LabelingPulseFlipAngle": Annotated[
        Positive[number],
        Maximum(360),
        Recommended,
    ],
    "LabelingPulseInterval": Annotated[
        Positive[number],
        Recommended,
    ],
})

ExtraPASLSchema = JSONSchema({
    "BolusCutOffFlag": Annotated[
        bool,
        Required,
    ],
    "PASLType": Annotated[
        str,
        Literal["FAIR", "EPISTAR", "PICORE"],
        Recommended,
    ],
    "LabelingSlabThickness": Annotated[
        Positive[number],
        Recommended,
    ],
    "BolusCutOffDelayTime": Annotated[
        Positive[number],
        Optional,
        # RequiredIf["BolusCutOffFlag is True"],
    ],
    "BolusCutOffTechnique": Annotated[
        str,
        Optional,
        # RequiredIf["BolusCutOffFlag is True"],
    ],
})

ExtraM0ASLSchema = JSONSchema({
    "IntendedFor": Annotated[
        str | list[str],
        Required,
    ],
    "AcquisitionVoxelSize": Annotated[
        tuple[Positive[number], Positive[number], Positive[number]],
        Recommended,
    ],
})


# ======================================================================
#                             B0 Field maps
# ======================================================================


B0fmapSchema = JSONSchema({
    **MRISchema,
    "IntendedFor": Annotated[
        str | list[str],
        Optional,
    ],
})

PhaseDiffB0fmapSchema = JSONSchema({
    **B0fmapSchema,
    "EchoTime1": Annotated[
        Positive[number],
        Required,
    ],
    "EchoTime2": Annotated[
        Positive[number],
        Required,
    ],
})

TwoPhaseB0fmapSchema = B0fmapSchema.copy()
TwoPhaseB0fmapSchema["EchoTime"] = Annotated[
    TwoPhaseB0fmapSchema["EchoTime"],
    Required
]

DirectB0fmapSchema = JSONSchema({
    **B0fmapSchema,
    "Units": Annotated[
        str,                # TODO: CMIXF validator
        Required,
    ],
})


PepolarB0fmapSchema = B0fmapSchema.copy()
PepolarB0fmapSchema["PhaseEncodingDirection"] = Annotated[
    PepolarB0fmapSchema["PhaseEncodingDirection"],
    Required
]
PepolarB0fmapSchema["TotalReadoutTime"] = Annotated[
    PepolarB0fmapSchema["TotalReadoutTime"],
    Optional,
    # RequiredIf["other methods for calculating readout time are not present"]
]
PepolarB0fmapSchema["EffectiveEchoSpacing"] = Annotated[
    PepolarB0fmapSchema["EffectiveEchoSpacing"],
    Optional,
    # RequiredIf["other methods for calculating readout time are not present"]
]


# ======================================================================
#                             B1 Field maps
# ======================================================================

TB1TFLSchema = TB1RFMSchema = TB1Schema = MRISchema

TB1DAMSchema = TB1Schema.copy()
TB1DAMSchema["FlipAngle"] = Annotated[
    TB1DAMSchema["FlipAngle"],
    Required
]

TB1EPISchema = TB1Schema.copy()
TB1EPISchema["EchoTime"] = Annotated[
    TB1EPISchema["EchoTime"],
    Required
]
TB1EPISchema["FlipAngle"] = Annotated[
    TB1EPISchema["FlipAngle"],
    Required
]
TB1EPISchema["TotalReadoutTime"] = Annotated[
    TB1EPISchema["TotalReadoutTime"],
    Required
]
TB1EPISchema["MixingTime"] = Annotated[
    TB1EPISchema["MixingTime"],
    Required
]

TB1AFISchema = TB1Schema.copy()
TB1AFISchema["RepetitionTimeExcitation"] = Annotated[
    TB1AFISchema["RepetitionTimeExcitation"],
    Required
]

TB1SRGESchema = TB1Schema.copy()
TB1SRGESchema["FlipAngle"] = Annotated[
    TB1SRGESchema["FlipAngle"],
    Required
]
TB1SRGESchema["InversionTime"] = Annotated[
    TB1SRGESchema["InversionTime"],
    Required
]
TB1SRGESchema["RepetitionTimeExcitation"] = Annotated[
    TB1SRGESchema["RepetitionTimeExcitation"],
    Required
]
TB1SRGESchema["RepetitionTimePreperation"] = Annotated[
    TB1SRGESchema["RepetitionTimePreperation"],
    Required
]
TB1SRGESchema["NumberShots"] = Annotated[
    TB1SRGESchema["NumberShots"],
    Required
]


RB1CORSchema = RB1mapSchema = RB1Schema = MRISchema

# ======================================================================
#                  D I R E C T O R Y   S C H E M A S
# ======================================================================

# ======================================================================
#                           Anatomical imaging
# ======================================================================


def make_schema(
    *patterns: list[str], schema: JSONSchema = MRISchema
) -> DirectorySchema:
    schema_dict = {}
    for pattern in patterns:
        schema_dict[_p(pattern + ext_nii)] = Annotated[
            NiftiFile,
            Optional,
        ]
        schema_dict[_p(pattern + ext_json)] = Annotated[
            JSONFile,
            JSONFileValidator(schema),
            Optional,
        ]
    return DirectorySchema(schema_dict)


# ----------------------------------------------------------------------
# Non-parametric structural MR images
# ----------------------------------------------------------------------

nonparam_anat_suffixes = (
    "FLAIR",
    "PDT2",
    "PDw",
    "T1w",
    "T2starw",
    "T2w",
    "angio",
    "inplaneT1",
    "inplaneT2",
)
nonparam_anat_file_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_({'|'.join(nonparam_anat_suffixes)})"
)
unit1_anat_file_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_echo-{bids_index})?"
    f"_UNIT1"
)

NonParamAnatDirectorySchema = make_schema(
    nonparam_anat_file_pattern,
    unit1_anat_file_pattern,
    schema=AnatSchema
)

# ----------------------------------------------------------------------
# Parametric structural MR images
# ----------------------------------------------------------------------

param_anat_suffixes = (
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
)

param_anat_file_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_chunk-{bids_index})?"
    f"_({'|'.join(nonparam_anat_suffixes)})"
)

ParamAnatDirectorySchema = make_schema(
    param_anat_file_pattern,
    schema=AnatSchema
)

# ----------------------------------------------------------------------
# Defacing masks
# ----------------------------------------------------------------------

defacing_anat_file_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_mod-{bids_label})?"
    f"(_chunk-{bids_index})?"
    f"_defacemask"
)

DefacingAnatDirectorySchema = make_schema(
    defacing_anat_file_pattern,
    schema=AnatSchema
)

# ----------------------------------------------------------------------
# Deprecated suffixes
# ----------------------------------------------------------------------

deprecated_anat_suffixes = (
    "FLASH",
    "PD",
    "T2star",
)
deprecated_anat_file_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_({'|'.join(deprecated_anat_suffixes)})"
)

DeprecatedAnatDirectorySchema = DirectorySchema({
    _p(deprecated_anat_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
        VersionSpecifier["<1.5.0"]
    ],
    _p(deprecated_anat_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(AnatSchema),
        Optional,
        VersionSpecifier["<1.5.0"]
    ],
})

# ----------------------------------------------------------------------
# Combine
# ----------------------------------------------------------------------

AnatDirectorySchema = DirectorySchema({
    **NonParamAnatDirectorySchema,
    **ParamAnatDirectorySchema,
    **DefacingAnatDirectorySchema,
    **DeprecatedAnatDirectorySchema,
})
AnatDirectory = Annotated[Directory, AnatDirectorySchema]


# ======================================================================
#                          Functional imaging
# ======================================================================


func_suffixes = (
    "bold",
    "cbv",
    "sbref",
)

func_prefix_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_task-{bids_label})"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_dir-{bids_label})?"
    f"(_run-{bids_index})?"
)

func_file_pattern = func_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_({'|'.join(func_suffixes)})"
)

events_func_file_pattern = func_prefix_pattern + "_events"

norf_func_file_pattern = func_prefix_pattern + (
    f"(_mod-{bids_label})?"
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_noRF"
)

phase_func_file_pattern = func_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_chunk-{bids_index})?"
    f"_phase"
)

physio_func_suffixes = ("physio", "stim")

physio_func_file_pattern = func_prefix_pattern + (
    f"(_recording-{bids_label})?"
    f"_({'|'.join(physio_func_suffixes)})"
)

FuncDirectorySchema = DirectorySchema({
    _p(func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        Optional,
    ],
    _p(norf_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(norf_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        Optional,
    ],
    _p(phase_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(phase_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        Optional,
    ],
    _p(events_func_file_pattern + ext_tsv): Annotated[
        TSVFile,
        Optional,
    ],
    _p(events_func_file_pattern + ext_json): Annotated[
        JSONFile,
        Optional,
    ],
    _p(physio_func_file_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        Optional,
    ],
    _p(physio_func_file_pattern + ext_json): Annotated[
        JSONFile,
        Optional,
    ],
})
FuncDirectory = Annotated[Directory, FuncDirectorySchema]


# ======================================================================
#                          Diffusion imaging
# ======================================================================


dwi_prefix_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_dir-{bids_label})?"
    f"(_run-{bids_index})?"
)

dwi_sbref_file_pattern = dwi_prefix_pattern + (
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_sbref"
)

dwi_file_pattern = dwi_prefix_pattern + (
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_dwi"
)

dwi_scanner_suffixes = (
    "ADC",
    "FA",
    "S0map",
    "colFA",
    "expADC",
    "trace",
)

dwi_scanner_file_pattern = dwi_prefix_pattern + (
    f"(_chunk-{bids_index})?"
    f"_({'|'.join(dwi_scanner_suffixes)})"
)

dwi_physio_suffixes = (
    "physio",
    "stim",
)

dwi_physio_file_pattern = dwi_prefix_pattern + (
    f"(_recording-{bids_label})?"
    f"_({'|'.join(dwi_physio_suffixes)})"
)

DwiDirectorySchema = DirectorySchema({
    _p(dwi_file_pattern + ext_bval): Annotated[
        BvalFile,
        Optional,
    ],
    _p(dwi_file_pattern + ext_bvec): Annotated[
        BvecFile,
        Optional,
    ],
    _p(dwi_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(dwi_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        Optional,
    ],
    _p(dwi_sbref_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(dwi_sbref_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        Optional,
    ],
    _p(dwi_scanner_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(dwi_scanner_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        Optional,
    ],
    _p(dwi_physio_file_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        Optional,
    ],
    _p(dwi_physio_file_pattern + ext_json): Annotated[
        JSONFile,
        Optional,
    ],
})
DwiDirectory = Annotated[Directory, DwiDirectorySchema]


# ======================================================================
#                         Arterial Spin Labeling
# ======================================================================


asl_prefix0_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_rec-{bids_label})?"
)

asl_prefix_pattern = asl_prefix0_pattern + (
    f"(_dir-{bids_label})?"
    f"(_run-{bids_index})?"
)

asl_suffixes = (
    "asl",
    "m0scan",
)

asl_pattern = asl_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"_({'|'.join(asl_suffixes)})"
)

asl_context_pattern = asl_prefix_pattern + (
    r"_aslcontext"
    r"\.tsv$"
)

asl_labeling_pattern = asl_prefix0_pattern + (
    f"(_run-{bids_index})?"
    f"_asllabeling"
    r"\.(tsv|png|tif)$"
)

asl_norf_pattern = asl_prefix_pattern + (
    f"(_mod-{bids_label})?"
    f"(_echo-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"_noRF"
)

asl_physio_suffixes = (
    "physio",
    "stim",
)

asl_physio_pattern = asl_prefix_pattern + (
    f"(_recording-{bids_label})?"
    f"_({'|'.join(asl_physio_suffixes)})"
)

AslContextSchema = JSONSchema({
    "volume_type": Annotated[
        str,
        Literal[
            "control",
            "label",
            "m0scan",
            "deltam",
            "cbf",
            "noRF",
            "n/a",
        ],
        Optional,
    ],
})

PerfDirectorySchema = DirectorySchema({
    _p(asl_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(asl_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(CommonASLSchema),
        Optional,
    ],
    _p(asl_context_pattern): Annotated[
        TSVFile,
        TSVFileValidator(AslContextSchema),
        Optional,
    ],
    _p(asl_labeling_pattern): Annotated[
        File,
        Optional,
    ],
    _p(asl_norf_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(asl_norf_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(CommonASLSchema),
        Optional,
    ],
    _p(asl_physio_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        Optional,
    ],
    _p(asl_physio_pattern + ext_json): Annotated[
        JSONFile,
        Optional,
    ],
})
PerfDirectory = Annotated[Directory, PerfDirectorySchema]


# ======================================================================
#                           Field maps
# ======================================================================

# ----------------------------------------------------------------------
# B0 Field maps
# ----------------------------------------------------------------------

b0_prefix_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_run-{bids_index})?"
    f"(_chunk-{bids_label})?"
)

b0_pepolar_prefix_pattern = b0_prefix_pattern + (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_dir-{bids_label})"
    f"(_run-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_label})?"
    f"_epi"
)

B0DirectorySchema = DirectorySchema({
    # Magnitude image(s)
    _p(b0_prefix_pattern + "_magnitude(1|2)?" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(b0_prefix_pattern + "_magnitude(1|2)?" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(B0fmapSchema),
        Optional,
    ],
    # Phase difference image
    _p(b0_prefix_pattern + "_phasediff" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(b0_prefix_pattern + "_phasediff" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(PhaseDiffB0fmapSchema),
        Optional,
    ],
    # Two phase images
    _p(b0_prefix_pattern + "_phase(1|2)" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(b0_prefix_pattern + "_phase(1|2)" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TwoPhaseB0fmapSchema),
        Optional,
    ],
    # Direct field map
    _p(b0_prefix_pattern + "_fieldmap" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(b0_prefix_pattern + "_fieldmap" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DirectB0fmapSchema),
        Optional,
    ],
    # PEPOLAR
    _p(b0_pepolar_prefix_pattern + ext_bval): Annotated[
        BvalFile,
        Optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_bvec): Annotated[
        BvecFile,
        Optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(PepolarB0fmapSchema),
        Optional,
    ],
})

# ----------------------------------------------------------------------
# B1+ (TB1) Field maps
# ----------------------------------------------------------------------

tb1_prefix_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
)

tb1_dam_file_pattern = tb1_prefix_pattern + (
    f"(_flip-{bids_index})"
    f"(_inv-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_TB1DAM"
)

tb1_epi_file_pattern = tb1_prefix_pattern + (
    f"(_echo-{bids_index})"
    f"(_flip-{bids_index})"
    f"(_inv-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_TB1EPI"
)

tb1_srgm_file_pattern = tb1_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_flip-{bids_index})"
    f"(_inv-{bids_index})"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_TB1SRGE"
)

tb1_map_file_pattern = tb1_prefix_pattern + (
    f"(_chunk-{bids_index})?"
    f"_TB1map"
)

tb1_other_prefix_pattern = tb1_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_flip-{bids_index})?"
    f"(_inv-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
)

TB1DirectorySchema = DirectorySchema({
    _p(tb1_dam_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_dam_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1DAMSchema),
        Optional,
    ],
    _p(tb1_epi_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_epi_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1EPISchema),
        Optional,
    ],
    _p(tb1_srgm_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_srgm_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1SRGESchema),
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1AFI" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1AFI" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1AFISchema),
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1TFL" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1TFL" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1TFLSchema),
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1RFM" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1RFM" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1RFMSchema),
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1map" + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1map" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1Schema),
        Optional,
    ],
})

# ----------------------------------------------------------------------
# B1+ (RB1) Field maps
# ----------------------------------------------------------------------

rb1_prefix_pattern = (
    f"^sub-{bids_label}"
    f"(_ses-{bids_label})?"
    f"(_acq-{bids_label})?"
    f"(_ce-{bids_label})?"
    f"(_rec-{bids_label})?"
    f"(_run-{bids_index})?"
)

rb1_cor_file_pattern = rb1_prefix_pattern + (
    f"(_echo-{bids_index})?"
    f"(_flip-{bids_index})?"
    f"(_inv-{bids_index})?"
    f"(_part-(mag|phase|real|imag))?"
    f"(_chunk-{bids_index})?"
    f"_RB1COR"
)


rb1_map_file_pattern = rb1_prefix_pattern + (
    f"(_chunk-{bids_index})?"
    f"_RB1map"
)


RB1DirectorySchema = DirectorySchema({
    _p(rb1_cor_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(rb1_cor_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(RB1CORSchema),
        Optional,
    ],
    _p(rb1_map_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    _p(rb1_map_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(RB1Schema),
        Optional,
    ],
})


# ----------------------------------------------------------------------
# Combine
# ----------------------------------------------------------------------

FmapDirectorySchema = DirectorySchema({
    **B0DirectorySchema,
    **TB1DirectorySchema,
    **RB1DirectorySchema,
})
FmapDirectory = Annotated[Directory, FmapDirectorySchema]
