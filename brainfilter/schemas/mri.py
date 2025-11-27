# stdlib
import re
from typing import Annotated, Literal, T

# internals
from brainfilter.re import (
    bids_label, bids_index, ext_json, ext_nii, ext_tsv, ext_tsvgz
)
from brainfilter.schemas.utils import (
    URI, Directory, NiftiFile, JSONFile, TSVFile, Positive, TSVGZFile
)
from brainfilter.validation import (
    DirectorySchema, JSONSchema, JSONFileValidator, Required, VersionSpecifier,
    Recommended, Optional, Deprecated,
    # RequiredIf, RecommendedIf
)
from brainfilter.validator_zoo import Maximum, Minimum

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
        float,
        Recommended,
        # RequiredIf[lambda *a: False],   # TODO: is_perf
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
        tuple[float, float, float],
        Optional,
        # RecommendedIf[lambda *a: False],   # TODO: has chunk-*
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
        # RecommendedIf[lambda *a: False],    # TODO: associated pet data
    ],
    "MRAcquisitionType": Annotated[
        str,
        Literal["1D, 2D, 3D"],
        Recommended,
        # RequiredIf[lambda *a: False],       # TODO: is under perf/
    ],
    "MTState": Annotated[
        bool,
        Optional,
        # RequiredIf[lambda *a: False],       # TODO: has mt-*
    ],
    "MTOffsetFrequency": Annotated[
        float,
        Optional,
    ],
    "MTPulseBandwidth": Annotated[
        float,
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
        float,
        Optional,
    ],
    "NumberShots": Annotated[
        int | tuple[int, int],
        Optional,
        # RequiredIf[lambda *a: False],       # TODO: is _MP2RAGE
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
        float,
        Optional,
    ],
    "SpoilingGradientMoment": Annotated[
        float,
        Optional,
    ],
    "SpoilingGradientDuration": Annotated[
        float,
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
        int | float,
        Optional,
        # RecommendedIf[lambda *a: False],    # TODO: has ParallelAcquisitionTechnique
    ],
    "ParallelReductionFactorOutOfPlane": Annotated[
        int | float,
        Optional,
        # RecommendedIf[lambda *a: False],    # TODO: has ParallelAcquisitionTechnique
    ],
    "ParallelAcquisitionTechnique": Annotated[
        str,
        Optional,
    ],
    "PartialFourier": Annotated[
        float,
        Optional,
    ],
    "PartialFourierDirection": Annotated[
        str,
        Optional,
        # RecommendedIf[lambda *a: False],    # TODO: has PartialFourier
    ],
    "EffectiveEchoSpacing": Annotated[
        float,
        Optional,
        # RecommendedIf[lambda *a: False],    # TODO: associated fmap data
    ],
    "MixingTime": Annotated[
        float,
        Optional,
        # RequiredIf[lambda *a: False],       # TODO: find which qMRI seqs use this
    ],
    "PhaseEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        Recommended,
        # RequiredIf[lambda *a: False],       # TODO: associated fmap data
    ],
    "TotalReadoutTime": Annotated[
        float,
        Recommended,
        # RequiredIf[lambda *a: False],       # TODO: blip-up/down fmap
    ],
})

TimingSchema = JSONSchema({
    "EchoTime": Annotated[
        float | list[float],
        Recommended,
        # RequiredIf[lambda *a: False],       # TODO: associated fmap or is ME-ASL
    ],
    "InversionTime": Annotated[
        float,
        Optional,
        # RequiredIf[lambda *a: False],       # TODO: has inv-*
    ],
    "DwellTime": Annotated[
        float,
        Recommended,
    ],
    "AcquisitionDuration": Annotated[
        Positive[float],
        Optional,
    ],
    "SliceTiming": Annotated[
        list[float],
        Recommended,
        # RequiredIf[lambda *a: False],       # TODO: ASL-2D + other
    ],
    "SliceEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        Optional,
    ],
})

ContrastSchema = JSONSchema({
    "FlipAngle": Annotated[
        float,
        Recommended,
        # RequiredIf["LookLocker is set to True"]
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
        dict[str, tuple[float, float, float]],
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
        Positive[float],
        Optional,
    ],
    "RepetitionTimePreparation": Annotated[
        Positive[float] | list[Positive[float]],
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
        Positive[float],
        Required,
        # MutuallyExclusive["VolumeTiming"],
    ],
    "VolumeTiming": Annotated[
        list[Positive[float]],
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
        Positive[float],
        Optional,
    ],
    "FrameAcquisitionDuration": Annotated[
        Positive[float],
        Optional,
        # RequiredIf["VolumeTiming but not SliceTiming"]
    ],
    "DelayAfterTrigger": Annotated[
        Positive[float],
        Optional,
    ],
    "AcquisitionDuration": Annotated[
        Positive[float],
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
        Positive[float],
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
        tuple[Positive[float], Positive[float], Positive[float]],
        Recommended,
    ],
    "LabelingOrientation": Annotated[
        str,
        Recommended,
    ],
    "LabelingDistance": Annotated[
        float,
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
        float,
        Minimum(0),
        Maximum(1),
        Optional,
    ],
    "M0Estimate": Annotated[
        Positive[float],
        Optional,
        # RequiredIf["M0Type is 'Estimate'"],
    ],
    "BackgroundSuppressionNumberPulses": Annotated[
        Positive[int],
        Optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "BackgroundSuppressionPulseTimes": Annotated[
        list[Positive[float]],
        Optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "VascularCrushingVENC": Annotated[
        Positive[float] | list[Positive[float]],
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
        Positive[float],
        Required,
    ],
    "LabelingPulseAverageGradient": Annotated[
        Positive[float],
        Recommended,
    ],
    "LabelingPulseMaximumGradient": Annotated[
        Positive[float],
        Recommended,
    ],
    "LabelingPulseAverageB1": Annotated[
        Positive[float],
        Recommended,
    ],
    "LabelingPulseDuration": Annotated[
        Positive[float],
        Recommended,
    ],
    "LabelingPulseFlipAngle": Annotated[
        Positive[float],
        Maximum(360),
        Recommended,
    ],
    "LabelingPulseInterval": Annotated[
        Positive[float],
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
        Positive[float],
        Recommended,
    ],
    "BolusCutOffDelayTime": Annotated[
        Positive[float],
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
        tuple[Positive[float], Positive[float], Positive[float]],
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
        Positive[float],
        Required,
    ],
    "EchoTime2": Annotated[
        Positive[float],
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

TB1SRGEScheme       \
    = TB1AFIScheme  \
    = TB1TFLScheme  \
    = TB1RFMScheme  \
    = TB1Schema     \
    = MRISchema

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

RB1CORSchema = RB1mapSchema = RB1Schema = MRISchema

# ======================================================================
#                  D I R E C T O R Y   S C H E M A S
# ======================================================================


def make_schema(
    *patterns: list[str], schema: JSONSchema = MRISchema
) -> DirectorySchema:
    schema_dict = {}
    for pattern in patterns:
        schema_dict[re.compile(pattern + ext_nii)] = Annotated[
            NiftiFile,
            Optional,
        ]
        schema_dict[re.compile(pattern + ext_json)] = Annotated[
            JSONFile,
            JSONFileValidator(schema),
            Optional,
        ]
    return DirectorySchema(schema_dict)


# ======================================================================
#                           Anatomical imaging
# ======================================================================

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

ParamAnatDirectorySchema = make_schema(param_anat_file_pattern, schema=AnatSchema)

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

DefacingAnatDirectorySchema = make_schema(defacing_anat_file_pattern, schema=AnatSchema)

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
    re.compile(deprecated_anat_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
        VersionSpecifier["<1.5.0"]
    ],
    re.compile(deprecated_anat_file_pattern + ext_json): Annotated[
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
    re.compile(func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    re.compile(func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(MRISchema),
        Optional,
    ],
    re.compile(norf_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    re.compile(norf_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(MRISchema),
        Optional,
    ],
    re.compile(phase_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        Optional,
    ],
    re.compile(phase_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(MRISchema),
        Optional,
    ],
    re.compile(events_func_file_pattern + ext_tsv): Annotated[
        TSVFile,
        Optional,
    ],
    re.compile(events_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(MRISchema),
        Optional,
    ],
    re.compile(physio_func_file_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        Optional,
    ],
    re.compile(physio_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(MRISchema),
        Optional,
    ],
})
