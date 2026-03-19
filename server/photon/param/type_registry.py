from typing import Any, Dict, Type

from server.photon.param.base import ParameterBase
from server.photon.param.bool_param import BooleanParameter
from server.photon.param.custom_param import CustomParameter
from server.photon.param.dict_param import DictionaryParameter
from server.photon.param.float32_param import Float32Parameter
from server.photon.param.float64_param import DoubleParameter
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.int64_param import Int64Parameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int8_slice_param import Int8SliceParameter
from server.photon.param.nil_param import NilParameter
from server.photon.param.object_slice_param import ObjectSliceParameter
from server.photon.param.parameter_type import ParameterType
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter


TYPE_REGISTRY: Dict[ParameterType, Type[ParameterBase[Any]]] = {
    ParameterType.NilType: NilParameter,
    ParameterType.BooleanType: BooleanParameter,
    ParameterType.Int8Type: Int8Parameter,
    ParameterType.Int32Type: Int32Parameter,
    ParameterType.Int64Type: Int64Parameter,
    ParameterType.Float32Type: Float32Parameter,
    ParameterType.DoubleType: DoubleParameter,
    ParameterType.StringType: StringParameter,
    ParameterType.Int8SliceType: Int8SliceParameter,
    ParameterType.SliceType: SliceParameter,
    ParameterType.ObjectSliceType: ObjectSliceParameter,
    ParameterType.DictionaryType: DictionaryParameter,
    ParameterType.Hashtable: HashtableParameter,
    ParameterType.Custom: CustomParameter,
}
