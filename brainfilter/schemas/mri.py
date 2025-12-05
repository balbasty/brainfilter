# stdlib
from numbers import Number as number
from re import compile as _p    # -> re.Pattern
from typing import Annotated, Literal

# internals
from brainfilter.re import (
    bids_label, bids_index,
    ext_json, ext_nii, ext_tsv, ext_tsvgz, ext_bval, ext_bvec
)
from brainfilter.schemas.utils import (
    Positive, Directory, File, URI,
    BvalFile, BvecFile, NiftiFile, JSONFile, TSVFile, TSVGZFile
)
from brainfilter.sdict import SDict
from brainfilter.validators import (
    DirectorySchema, JSONSchema, JSONFileValidator, TSVFileValidator,
    required, recommended, optional, deprecated,
    # RequiredIf, RecommendedIf,
)
from brainfilter.versioning import VersionSpecifier
from brainfilter.adaptors import ValueInRange


# ======================================================================
#                         J S O N   S C H E M A S
# ======================================================================

ScannerHardwareSchema = JSONSchema({
    "Manufacturer": Annotated[
        str,
        recommended,
    ],
    "ManufacturersModelName": Annotated[
        str,
        recommended,
    ],
    "DeviceSerialNumber": Annotated[
        str,
        recommended,
    ],
    "StationName": Annotated[
        str,
        recommended,
    ],
    "SoftwareVersions": Annotated[
        str,
        recommended,
    ],
    "HardcopyDeviceSoftwareVersion": Annotated[
        str,
        deprecated,
    ],
    "MagneticFieldStrength": Annotated[
        number,
        recommended,
        # RequiredIf["Is under perf/"],
    ],
    "ReceiveCoilName": Annotated[
        str,
        recommended,
    ],
    "ReceiveCoilActiveElements": Annotated[
        str,
        recommended,
    ],
    "NumberReceiveCoilActiveElements": Annotated[
        int,
        optional,
    ],
    "GradientSetType": Annotated[
        str,
        optional,
    ],
    "MRTransmitCoilSequence": Annotated[
        str,
        optional,
    ],
    "MatrixCoilMode": Annotated[
        str,
        recommended,
    ],
    "CoilCombinationMethod": Annotated[
        str,
        recommended,
    ],
    "NumberTransmitCoilActiveElements": Annotated[
        int,
        optional,
    ],
    "TablePosition": Annotated[
        tuple[number, number, number],
        optional,
        # RecommendedIf["has chunk-*"],
    ],
})

InstitutionInformationSchema = JSONSchema({
    "InstitutionName": Annotated[
        str,
        recommended,
    ],
    "InstitutionAddress": Annotated[
        str,
        recommended,
    ],
    "InstitutionalDepartmentName": Annotated[
        str,
        recommended,
    ],
})

SequenceSpecificsSchema = JSONSchema({
    "PulseSequenceType": Annotated[
        str,
        recommended,
    ],
    "ScanningSequence": Annotated[
        str | list[str],
        recommended,
    ],
    "SequenceVariant": Annotated[
        str | list[str],
        recommended,
    ],
    "ScanOptions": Annotated[
        str | list[str],
        optional,
    ],
    "SequenceName": Annotated[
        str,
        recommended,
    ],
    "PulseSequenceDetails": Annotated[
        str,
        recommended,
    ],
    "NonlinearGradientCorrection": Annotated[
        bool,
        optional,
        # RecommendedIf["has associated pet data"],
    ],
    "MRAcquisitionType": Annotated[
        str,
        Literal["1D, 2D, 3D"],
        recommended,
        # RequiredIf["is under perf/"],
    ],
    "MTState": Annotated[
        bool,
        optional,
        # RequiredIf["has mt-*"],
    ],
    "MTOffsetFrequency": Annotated[
        number,
        optional,
    ],
    "MTPulseBandwidth": Annotated[
        number,
        optional,
    ],
    "MTNumberOfPulses": Annotated[
        int,
        optional,
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
        optional,
    ],
    "MTPulseDuration": Annotated[
        number,
        optional,
    ],
    "NumberShots": Annotated[
        int | tuple[int, int],
        optional,
        # RequiredIf["is _MP2RAGE"],
    ],
    "SpoilingState": Annotated[
        bool,
        optional,
    ],
    "SpoilingType": Annotated[
        str,
        Literal["RF", "GRADIENT", "COMBINED"],
        optional,
    ],
    "SpoilingRFPhaseIncrement": Annotated[
        number,
        optional,
    ],
    "SpoilingGradientMoment": Annotated[
        number,
        optional,
    ],
    "SpoilingGradientDuration": Annotated[
        number,
        optional,
    ],
    "WaterSuppression": Annotated[
        bool,
        optional,
    ],
    "WaterSuppressionTechnique": Annotated[
        str,
        optional,
    ],
    "B0ShimmingTechnique": Annotated[
        str,
        optional,
    ],
    "B1ShimmingTechnique": Annotated[
        str,
        optional,
    ],
})

SpatialEncodingSchema = JSONSchema({
    "ParallelReductionFactorInPlane": Annotated[
        int | number,
        optional,
        # RecommendedIf["has ParallelAcquisitionTechnique"],
    ],
    "ParallelReductionFactorOutOfPlane": Annotated[
        int | number,
        optional,
        # RecommendedIf["has ParallelAcquisitionTechnique"],
    ],
    "ParallelAcquisitionTechnique": Annotated[
        str,
        optional,
    ],
    "PartialFourier": Annotated[
        number,
        optional,
    ],
    "PartialFourierDirection": Annotated[
        str,
        optional,
        # RecommendedIf["has PartialFourier"],
    ],
    "EffectiveEchoSpacing": Annotated[
        number,
        optional,
        # RecommendedIf["has associated fmap data"],
    ],
    "MixingTime": Annotated[
        number,
        optional,
        # RequiredIf["qMRI sequence needs this"],
    ],
    "PhaseEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        recommended,
        # RequiredIf["has associated fmap data"],
    ],
    "TotalReadoutTime": Annotated[
        number,
        recommended,
        # RequiredIf["has blip-up/down fmap"],
    ],
})

TimingSchema = JSONSchema({
    "EchoTime": Annotated[
        number | list[number],
        recommended,
        # RequiredIf["has associated fmap or is ME-ASL"],
    ],
    "InversionTime": Annotated[
        number,
        optional,
        # RequiredIf["has inv-*"],
    ],
    "DwellTime": Annotated[
        number,
        recommended,
    ],
    "AcquisitionDuration": Annotated[
        Positive[number],
        optional,
    ],
    "SliceTiming": Annotated[
        list[number],
        recommended,
        # RequiredIf["is ASL-2D + other"],
    ],
    "SliceEncodingDirection": Annotated[
        str,
        Literal["i", "i-", "j", "j-", "k", "k-"],
        optional,
    ],
})

ContrastSchema = JSONSchema({
    "FlipAngle": Annotated[
        number,
        recommended,
        # RequiredIf["LookLocker is True"]
    ],
    "NegativeContrast": Annotated[
        bool,
        optional,
    ],
})

SliceAccelerationSchema = JSONSchema({
    "MultibandAccelerationFactor": Annotated[
        int,
        optional,
    ],
})

AnatomicalLandmarksSchema = JSONSchema({
    "AnatomicalLandmarkCoordinates": Annotated[
        dict[str, tuple[number, number, number]],
        recommended,
    ],
})

B0Schema = JSONSchema({
    "B0FieldIdentifier": Annotated[
        str | list[str],
        recommended,
    ],
    "B0FieldSource": Annotated[
        str | list[str],
        recommended,
    ],
})

TissueSchema = JSONSchema({
    "BodyPart": Annotated[
        str,
        optional,
    ],
    "BodyPartDetails": Annotated[
        str,
        optional,
    ],
    "BodyPartDetailsOntology": Annotated[
        URI,
        optional,
    ],
})

DeidentificationMethodCodeSequenceSchema = JSONSchema({
    "CodeValue": Annotated[
        str,
        recommended,
    ],
    "CodeMeaning": Annotated[
        str,
        recommended,
    ],
    "CodingSchemeDesignator": Annotated[
        str,
        recommended,
    ],
    "CodingSchemeVersion": Annotated[
        str,
        recommended,
    ]
})


class DeidentificationMethodCodeSequence(
    SDict, schema=DeidentificationMethodCodeSequenceSchema
):
    ...


DeidentificationSchema = JSONSchema({
    "DeidentificationMethod": Annotated[
        list[str],
        optional,
    ],
    "DeidentificationMethodCodeSequence": Annotated[
        list[DeidentificationMethodCodeSequence],
        optional,
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
        optional,
        # RecommendedIf["task- in filename"],
    ],
    "TaskDescription": Annotated[
        str,
        optional,
        # RecommendedIf["task- in filename"],
    ],
    "Instructions": Annotated[
        str,
        optional,
        # RecommendedIf["task- in filename"],
    ],
})

ExtraAnatSchema = JSONSchema({
    "ContrastBolusAgent": Annotated[
        str,
        optional,
    ],
    "RepetitionTimeExcitation": Annotated[
        Positive[number],
        optional,
    ],
    "RepetitionTimePreparation": Annotated[
        Positive[number] | list[Positive[number]],
        optional,
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
        required,
        # MutuallyExclusive["VolumeTiming"],
    ],
    "VolumeTiming": Annotated[
        list[Positive[number]],
        required,
        # MutuallyExclusive["RepetitionTime"],
    ],
    "TaskName": Annotated[
        str,
        required,
    ],
})

RecommendedFuncSchema = JSONSchema({
    "NumberOfVolumesDiscardedByScanner": Annotated[
        Positive[int],
        recommended,
    ],
    "NumberOfVolumesDiscardedByUser": Annotated[
        Positive[int],
        recommended,
    ],
    "DelayTime": Annotated[
        Positive[number],
        optional,
    ],
    "FrameAcquisitionDuration": Annotated[
        Positive[number],
        optional,
        # RequiredIf["VolumeTiming but not SliceTiming"]
    ],
    "DelayAfterTrigger": Annotated[
        Positive[number],
        optional,
    ],
    "AcquisitionDuration": Annotated[
        Positive[number],
        deprecated,
    ],
})

TaskFuncSchema = JSONSchema({
    "Instructions": Annotated[
        str,
        recommended,
    ],
    "TaskDescription": Annotated[
        str,
        recommended,
    ],
    "CogAtlasID": Annotated[
        URI,
        recommended,
    ],
    "CogPOID": Annotated[
        URI,
        recommended,
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
        optional,
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
        required,
    ],
    "PostLabelingDelay": Annotated[
        Positive[number],
        required,
    ],
    "BackgroundSuppression": Annotated[
        bool,
        required,
    ],
    "M0Type": Annotated[
        str,
        Literal["Separate", "Included", "Estimate", "Absent"],
        required,
    ],
    "TotalAcquiredPairs": Annotated[
        Positive[int],
        recommended,
    ],
    "VascularCrushing": Annotated[
        bool,
        recommended,
    ],
    "AcquisitionVoxelSize": Annotated[
        tuple[Positive[number], Positive[number], Positive[number]],
        recommended,
    ],
    "LabelingOrientation": Annotated[
        str,
        recommended,
    ],
    "LabelingDistance": Annotated[
        number,
        recommended,
    ],
    "LabelingLocationDescription": Annotated[
        str,
        recommended,
    ],
    "LookLocker": Annotated[
        bool,
        optional,
    ],
    "LabelingEfficiency": Annotated[
        number,
        ValueInRange(0, 1),
        optional,
    ],
    "M0Estimate": Annotated[
        Positive[number],
        optional,
        # RequiredIf["M0Type is 'Estimate'"],
    ],
    "BackgroundSuppressionNumberPulses": Annotated[
        Positive[int],
        optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "BackgroundSuppressionPulseTimes": Annotated[
        list[Positive[number]],
        optional,
        # RecommendedIf["BackgroundSuppression is True"],
    ],
    "VascularCrushingVENC": Annotated[
        Positive[number] | list[Positive[number]],
        optional,
        # RecommendedIf["VascularCrushing is True"],
    ],
})

ExtraPCASLSchema = JSONSchema({
    "PCASLType": Annotated[
        str,
        Literal["balanced", "unbalanced"],
        optional,
        # RecommendedIf["ArterialSpinLabelingType is 'PCASL'"],
    ],
    "CASLType": Annotated[
        str,
        Literal["single-coil", "double-coil"],
        optional,
        # RecommendedIf["ArterialSpinLabelingType is 'CASL'"],
    ],
    "LabelingDuration": Annotated[
        Positive[number],
        required,
    ],
    "LabelingPulseAverageGradient": Annotated[
        Positive[number],
        recommended,
    ],
    "LabelingPulseMaximumGradient": Annotated[
        Positive[number],
        recommended,
    ],
    "LabelingPulseAverageB1": Annotated[
        Positive[number],
        recommended,
    ],
    "LabelingPulseDuration": Annotated[
        Positive[number],
        recommended,
    ],
    "LabelingPulseFlipAngle": Annotated[
        Positive[number],
        ValueInRange(0, 360),
        recommended,
    ],
    "LabelingPulseInterval": Annotated[
        Positive[number],
        recommended,
    ],
})

ExtraPASLSchema = JSONSchema({
    "BolusCutOffFlag": Annotated[
        bool,
        required,
    ],
    "PASLType": Annotated[
        str,
        Literal["FAIR", "EPISTAR", "PICORE"],
        recommended,
    ],
    "LabelingSlabThickness": Annotated[
        Positive[number],
        recommended,
    ],
    "BolusCutOffDelayTime": Annotated[
        Positive[number],
        optional,
        # RequiredIf["BolusCutOffFlag is True"],
    ],
    "BolusCutOffTechnique": Annotated[
        str,
        optional,
        # RequiredIf["BolusCutOffFlag is True"],
    ],
})

ExtraM0ASLSchema = JSONSchema({
    "IntendedFor": Annotated[
        str | list[str],
        required,
    ],
    "AcquisitionVoxelSize": Annotated[
        tuple[Positive[number], Positive[number], Positive[number]],
        recommended,
    ],
})


# ======================================================================
#                             B0 Field maps
# ======================================================================


B0fmapSchema = JSONSchema({
    **MRISchema,
    "IntendedFor": Annotated[
        str | list[str],
        optional,
    ],
})

PhaseDiffB0fmapSchema = JSONSchema({
    **B0fmapSchema,
    "EchoTime1": Annotated[
        Positive[number],
        required,
    ],
    "EchoTime2": Annotated[
        Positive[number],
        required,
    ],
})

TwoPhaseB0fmapSchema = B0fmapSchema.copy()
TwoPhaseB0fmapSchema["EchoTime"] = Annotated[
    TwoPhaseB0fmapSchema["EchoTime"],
    required
]

DirectB0fmapSchema = JSONSchema({
    **B0fmapSchema,
    "Units": Annotated[
        str,                # TODO: CMIXF validator
        required,
    ],
})


PepolarB0fmapSchema = B0fmapSchema.copy()
PepolarB0fmapSchema["PhaseEncodingDirection"] = Annotated[
    PepolarB0fmapSchema["PhaseEncodingDirection"],
    required
]
PepolarB0fmapSchema["TotalReadoutTime"] = Annotated[
    PepolarB0fmapSchema["TotalReadoutTime"],
    optional,
    # RequiredIf["other methods for calculating readout time are not present"]
]
PepolarB0fmapSchema["EffectiveEchoSpacing"] = Annotated[
    PepolarB0fmapSchema["EffectiveEchoSpacing"],
    optional,
    # RequiredIf["other methods for calculating readout time are not present"]
]


# ======================================================================
#                             B1 Field maps
# ======================================================================

TB1TFLSchema = TB1RFMSchema = TB1Schema = AnatSchema

TB1DAMSchema = TB1Schema.copy()
TB1DAMSchema["FlipAngle"] = Annotated[
    TB1DAMSchema["FlipAngle"],
    required
]

TB1EPISchema = TB1Schema.copy()
TB1EPISchema["EchoTime"] = Annotated[
    TB1EPISchema["EchoTime"],
    required
]
TB1EPISchema["FlipAngle"] = Annotated[
    TB1EPISchema["FlipAngle"],
    required
]
TB1EPISchema["TotalReadoutTime"] = Annotated[
    TB1EPISchema["TotalReadoutTime"],
    required
]
TB1EPISchema["MixingTime"] = Annotated[
    TB1EPISchema["MixingTime"],
    required
]

TB1AFISchema = TB1Schema.copy()
TB1AFISchema["RepetitionTimeExcitation"] = Annotated[
    TB1AFISchema["RepetitionTimeExcitation"],
    required
]

TB1SRGESchema = TB1Schema.copy()
TB1SRGESchema["FlipAngle"] = Annotated[
    TB1SRGESchema["FlipAngle"],
    required
]
TB1SRGESchema["InversionTime"] = Annotated[
    TB1SRGESchema["InversionTime"],
    required
]
TB1SRGESchema["RepetitionTimeExcitation"] = Annotated[
    TB1SRGESchema["RepetitionTimeExcitation"],
    required
]
TB1SRGESchema["RepetitionTimePreperation"] = Annotated[
    Positive[number],
    required
]
TB1SRGESchema["NumberShots"] = Annotated[
    TB1SRGESchema["NumberShots"],
    required
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
            optional,
        ]
        schema_dict[_p(pattern + ext_json)] = Annotated[
            JSONFile,
            JSONFileValidator(schema),
            optional,
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
        optional,
        VersionSpecifier["<1.5.0"]
    ],
    _p(deprecated_anat_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(AnatSchema),
        optional,
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
        optional,
    ],
    _p(func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        optional,
    ],
    _p(norf_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(norf_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        optional,
    ],
    _p(phase_func_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(phase_func_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(FuncSchema),
        optional,
    ],
    _p(events_func_file_pattern + ext_tsv): Annotated[
        TSVFile,
        optional,
    ],
    _p(events_func_file_pattern + ext_json): Annotated[
        JSONFile,
        optional,
    ],
    _p(physio_func_file_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        optional,
    ],
    _p(physio_func_file_pattern + ext_json): Annotated[
        JSONFile,
        optional,
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
        optional,
    ],
    _p(dwi_file_pattern + ext_bvec): Annotated[
        BvecFile,
        optional,
    ],
    _p(dwi_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(dwi_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        optional,
    ],
    _p(dwi_sbref_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(dwi_sbref_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        optional,
    ],
    _p(dwi_scanner_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(dwi_scanner_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DWISchema),
        optional,
    ],
    _p(dwi_physio_file_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        optional,
    ],
    _p(dwi_physio_file_pattern + ext_json): Annotated[
        JSONFile,
        optional,
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
        optional,
    ],
})

PerfDirectorySchema = DirectorySchema({
    _p(asl_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(asl_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(CommonASLSchema),
        optional,
    ],
    _p(asl_context_pattern): Annotated[
        TSVFile,
        TSVFileValidator(AslContextSchema),
        optional,
    ],
    _p(asl_labeling_pattern): Annotated[
        File,
        optional,
    ],
    _p(asl_norf_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(asl_norf_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(CommonASLSchema),
        optional,
    ],
    _p(asl_physio_pattern + ext_tsvgz): Annotated[
        TSVGZFile,
        optional,
    ],
    _p(asl_physio_pattern + ext_json): Annotated[
        JSONFile,
        optional,
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
        optional,
    ],
    _p(b0_prefix_pattern + "_magnitude(1|2)?" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(B0fmapSchema),
        optional,
    ],
    # Phase difference image
    _p(b0_prefix_pattern + "_phasediff" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(b0_prefix_pattern + "_phasediff" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(PhaseDiffB0fmapSchema),
        optional,
    ],
    # Two phase images
    _p(b0_prefix_pattern + "_phase(1|2)" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(b0_prefix_pattern + "_phase(1|2)" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TwoPhaseB0fmapSchema),
        optional,
    ],
    # Direct field map
    _p(b0_prefix_pattern + "_fieldmap" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(b0_prefix_pattern + "_fieldmap" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(DirectB0fmapSchema),
        optional,
    ],
    # PEPOLAR
    _p(b0_pepolar_prefix_pattern + ext_bval): Annotated[
        BvalFile,
        optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_bvec): Annotated[
        BvecFile,
        optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(b0_pepolar_prefix_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(PepolarB0fmapSchema),
        optional,
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
        optional,
    ],
    _p(tb1_dam_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1DAMSchema),
        optional,
    ],
    _p(tb1_epi_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_epi_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1EPISchema),
        optional,
    ],
    _p(tb1_srgm_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_srgm_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1SRGESchema),
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1AFI" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1AFI" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1AFISchema),
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1TFL" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1TFL" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1TFLSchema),
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1RFM" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1RFM" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1RFMSchema),
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1map" + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(tb1_other_prefix_pattern + "_TB1map" + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(TB1Schema),
        optional,
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
        optional,
    ],
    _p(rb1_cor_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(RB1CORSchema),
        optional,
    ],
    _p(rb1_map_file_pattern + ext_nii): Annotated[
        NiftiFile,
        optional,
    ],
    _p(rb1_map_file_pattern + ext_json): Annotated[
        JSONFile,
        JSONFileValidator(RB1Schema),
        optional,
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
