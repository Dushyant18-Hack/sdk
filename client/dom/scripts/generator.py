#!/usr/bin/python
# Copyright (c) 2012, the Dart project authors.  Please see the AUTHORS file
# for details. All rights reserved. Use of this source code is governed by a
# BSD-style license that can be found in the LICENSE file.

"""This module provides shared functionality for systems to generate
Dart APIs from the IDL database."""

import re

# IDL->Dart primitive types conversion.
_idl_to_dart_type_conversions = {
    'any': 'Object',
    'any[]': 'List',
    'custom': 'Dynamic',
    'boolean': 'bool',
    'DOMObject': 'Object',
    'DOMString': 'String',
    'DOMStringList': 'List<String>',
    'DOMTimeStamp': 'int',
    'Date': 'Date',
    # Map to num to enable callers to pass in Dart int, rational
    # types.  Our implementations will need to convert these to
    # doubles or floats as needed.
    'double': 'num',
    'float': 'num',
    'int': 'int',
    # Map to extra precision - int is a bignum in Dart.
    'long': 'int',
    'long long': 'int',
    'object': 'Object',
    # Map to extra precision - int is a bignum in Dart.
    'short': 'int',
    'string': 'String',
    'void': 'void',
    'Array': 'List',
    'sequence': 'List',
    # TODO(sra): Come up with some meaningful name so that where this appears in
    # the documentation, the user is made aware that only a limited subset of
    # serializable types are actually permitted.
    'SerializedScriptValue': 'Dynamic',
    # TODO(vsm): Automatically recognize types defined in src.
    'TimeoutHandler': 'TimeoutHandler',
    'RequestAnimationFrameCallback': 'RequestAnimationFrameCallback',

    # TODO(sra): Flags is really a dictionary: {create:bool, exclusive:bool}
    # http://dev.w3.org/2009/dap/file-system/file-dir-sys.html#the-flags-interface
    'WebKitFlags': 'Object',
    }

_dart_to_idl_type_conversions = dict((v,k) for k, v in
                                     _idl_to_dart_type_conversions.iteritems())

_pure_interfaces = set([
    'ElementTimeControl',
    'ElementTraversal',
    'MediaQueryListListener',
    'NodeSelector',
    'SVGExternalResourcesRequired',
    'SVGFilterPrimitiveStandardAttributes',
    'SVGFitToViewBox',
    'SVGLangSpace',
    'SVGLocatable',
    'SVGStylable',
    'SVGTests',
    'SVGTransformable',
    'SVGURIReference',
    'SVGViewSpec',
    'SVGZoomAndPan'])

def IsPureInterface(interface_name):
  return interface_name in _pure_interfaces

#
# Identifiers that are used in the IDL than need to be treated specially because
# *some* JavaScript processors forbid them as properties.
#
_javascript_keywords = ['delete', 'continue']

#
# Interface version of the DOM needs to delegate typed array constructors to a
# factory provider.
#
interface_factories = {
    'Float32Array': '_TypedArrayFactoryProvider',
    'Float64Array': '_TypedArrayFactoryProvider',
    'Int8Array': '_TypedArrayFactoryProvider',
    'Int16Array': '_TypedArrayFactoryProvider',
    'Int32Array': '_TypedArrayFactoryProvider',
    'Uint8Array': '_TypedArrayFactoryProvider',
    'Uint16Array': '_TypedArrayFactoryProvider',
    'Uint32Array': '_TypedArrayFactoryProvider',
    'Uint8ClampedArray': '_TypedArrayFactoryProvider',
}

#
# Custom methods that must be implemented by hand.
#
_custom_methods = set([
    ('DOMWindow', 'setInterval'),
    ('DOMWindow', 'setTimeout'),
    ('WorkerContext', 'setInterval'),
    ('WorkerContext', 'setTimeout'),
    ('CanvasRenderingContext2D', 'setFillStyle'),
    ('CanvasRenderingContext2D', 'setStrokeStyle'),
    ('CanvasRenderingContext2D', 'setFillStyle'),
    ])

#
# Custom getters that must be implemented by hand.
#
_custom_getters = set([
    ('DOMWindow', 'localStorage'),
    ])

#
# Custom native specs for the Frog dom.
#
_frog_dom_custom_native_specs = {
    # Decorate the singleton Console object, if present (workers do not have a
    # console).
    'Console': "=(typeof console == 'undefined' ? {} : console)",

    # DOMWindow aliased with global scope.
    'DOMWindow': '@*DOMWindow',
}

#
# Simple method substitution when one method had different names on different
# browsers, but are otherwise identical.  The alternates are tried in order and
# the first one defined is used.
#
# This can be probably be removed when Chrome renames initWebKitWheelEvent to
# initWheelEvent.
#
_alternate_methods = {
    ('WheelEvent', 'initWheelEvent'): ['initWebKitWheelEvent', 'initWheelEvent']
}

def ConvertPrimitiveType(type_name):
  if type_name.startswith('unsigned '):
    type_name = type_name[len('unsigned '):]

  if type_name in _idl_to_dart_type_conversions:
    # Primitive type conversion
    return _idl_to_dart_type_conversions[type_name]
  return None

def IsPrimitiveType(type_name):
  return (ConvertPrimitiveType(type_name) is not None or
          type_name in _dart_to_idl_type_conversions)

def MaybeListElementTypeName(type_name):
  """Returns the List element type T from string of form "List<T>", or None."""
  match = re.match(r'List<(\w*)>$', type_name)
  if match:
    return match.group(1)
  return None

def MaybeListElementType(interface):
  """Returns the List element type T, or None in interface does not implement
  List<T>.
  """
  for parent in interface.parents:
    element_type = MaybeListElementTypeName(parent.type.id)
    if element_type:
      return element_type
  return None

def MaybeTypedArrayElementType(interface):
  """Returns the typed array element type, or None in interface is not a
  TypedArray.
  """
  # Typed arrays implement ArrayBufferView and List<T>.
  for parent in interface.parents:
    if  parent.type.id == 'ArrayBufferView':
      return MaybeListElementType(interface)
    if  parent.type.id == 'Uint8Array':
      return 'int'
  return None

def MakeNativeSpec(javascript_binding_name):
  if javascript_binding_name in _frog_dom_custom_native_specs:
    return _frog_dom_custom_native_specs[javascript_binding_name]
  else:
    # Make the class 'hidden' so it is dynamically patched at runtime.  This
    # is useful not only for browser compat, but to allow code that links
    # against dart:dom to load in a worker isolate.
    return '*' + javascript_binding_name


def MatchSourceFilter(filter, thing):
  if not filter:
    return True
  else:
    return any(token in thing.annotations for token in filter)

def AnalyzeOperation(interface, operations):
  """Makes operation calling convention decision for a set of overloads.

  Returns: An OperationInfo object.
  """

  # Zip together arguments from each overload by position, then convert
  # to a dart argument.

  # Given a list of overloaded arguments, choose a suitable name.
  def OverloadedName(args):
    return '_OR_'.join(sorted(set(arg.id for arg in args)))

  # Given a list of overloaded arguments, choose a suitable type.
  def OverloadedType(args):
    typeIds = sorted(set(arg.type.id for arg in args))
    if len(typeIds) == 1:
      return typeIds[0]
    else:
      return TypeName(typeIds, interface)

  # Given a list of overloaded arguments, render a dart argument.
  def DartArg(args):
    filtered = filter(None, args)
    optional = any(not arg or arg.is_optional for arg in args)
    type = OverloadedType(filtered)
    name = OverloadedName(filtered)
    if optional:
      return (name, type, 'null')
    else:
      return (name, type, None)

  args = map(lambda *args: DartArg(args),
             *(op.arguments for op in operations))

  info = OperationInfo()
  info.overloads = operations
  info.declared_name = operations[0].id
  info.name = operations[0].ext_attrs.get('DartName', info.declared_name)
  info.js_name = info.declared_name
  info.type_name = operations[0].type.id   # TODO: widen.
  info.arg_infos = args
  return info

def RecognizeCallback(interface):
  """Returns the info for the callback method if the interface smells like a
  callback.
  """
  if 'Callback' not in interface.ext_attrs: return None
  handlers = [op for op in interface.operations if op.id == 'handleEvent']
  if not handlers: return None
  if not (handlers == interface.operations): return None
  return AnalyzeOperation(interface, handlers)

def IsDartListType(type):
  return type == 'List' or type.startswith('List<')

def IsDartCollectionType(type):
  return IsDartListType(type)

def FindMatchingAttribute(interface, attr1):
  matches = [attr2 for attr2 in interface.attributes
             if attr1.id == attr2.id
             and attr1.is_fc_getter == attr2.is_fc_getter
             and attr1.is_fc_setter == attr2.is_fc_setter]
  if matches:
    assert len(matches) == 1
    return matches[0]
  return None

class OperationInfo(object):
  """Holder for various derived information from a set of overloaded operations.

  Attributes:
    overloads: A list of IDL operation overloads with the same name.
    name: A string, the simple name of the operation.
    type_name: A string, the name of the return type of the operation.
    arg_infos: A list of (name, type, default_value) tuples.
        default_value is None for mandatory arguments.
  """

  def ParametersInterfaceDeclaration(self):
    """Returns a formatted string declaring the parameters for the interface."""
    return self._FormatArgs(self.arg_infos, True)

  def ParametersImplementationDeclaration(self, rename_type=None):
    """Returns a formatted string declaring the parameters for the
    implementation.

    Args:
      rename_type: A function that allows the types to be renamed.
    """
    args = self.arg_infos
    if rename_type:
      args = [(name, rename_type(type), default)
              for (name, type, default) in args]
    return self._FormatArgs(args, False)

  def ParametersAsArgumentList(self):
    """Returns a formatted string declaring the parameters names as an argument
    list.
    """
    return ', '.join(map(lambda arg_info: arg_info[0], self.arg_infos))

  def _FormatArgs(self, args, is_interface):
    def FormatArg(arg_info):
      """Returns an argument declaration fragment for an argument info tuple."""
      (name, type, default) = arg_info
      if default:
        return '%s %s = %s' % (type, name, default)
      else:
        return '%s %s' % (type, name)

    required = []
    optional = []
    for (name, type, default) in args:
      if default:
        if is_interface:
          optional.append((name, type, None))  # Default values illegal.
        else:
          optional.append((name, type, default))
      else:
        if optional:
          raise Exception('Optional arguments cannot precede required ones: '
                          + str(args))
        required.append((name, type, None))
    argtexts = map(FormatArg, required)
    if optional:
      argtexts.append('[' + ', '.join(map(FormatArg, optional)) + ']')
    return ', '.join(argtexts)


def AttributeOutputOrder(a, b):
  """Canonical output ordering for attributes."""
    # Getters before setters:
  if a.id < b.id: return -1
  if a.id > b.id: return 1
  if a.is_fc_setter < b.is_fc_setter: return -1
  if a.is_fc_setter > b.is_fc_setter: return 1
  return 0

def ConstantOutputOrder(a, b):
  """Canonical output ordering for constants."""
  if a.id < b.id: return -1
  if a.id > b.id: return 1
  return 0


def _FormatNameList(names):
  """Returns JavaScript array literal expression with one name per line."""
  #names = sorted(names)
  if len(names) <= 1:
    expression_string = str(names)  # e.g.  ['length']
  else:
    expression_string = ',\n   '.join(str(names).split(','))
    expression_string = expression_string.replace('[', '[\n    ')
  return expression_string


def IndentText(text, indent):
  """Format lines of text with indent."""
  def FormatLine(line):
    if line.strip():
      return '%s%s\n' % (indent, line)
    else:
      return '\n'
  return ''.join(FormatLine(line) for line in text.split('\n'))

# Given a sorted sequence of type identifiers, return an appropriate type
# name
def TypeName(typeIds, interface):
  # Dynamically type this field for now.
  return 'var'

# ------------------------------------------------------------------------------

class IDLTypeInfo(object):
  def __init__(self, idl_type, native_type=None, ref_counted=True,
               has_dart_wrapper=True, conversion_template=None,
               custom_to_dart=False):
    self._idl_type = idl_type
    self._native_type = native_type
    self._ref_counted = ref_counted
    self._has_dart_wrapper = has_dart_wrapper
    self._conversion_template = conversion_template
    self._custom_to_dart = custom_to_dart

  def idl_type(self):
    return self._idl_type

  def native_type(self):
    if self._native_type:
      return self._native_type
    return self._idl_type

  def parameter_adapter_info(self):
    native_type = self.native_type()
    if self._ref_counted:
      native_type = 'RefPtr< %s >' % native_type
    if self._has_dart_wrapper:
      wrapper_type = 'Dart%s' % self.idl_type()
      adapter_type = 'ParameterAdapter<%s, %s>' % (native_type, wrapper_type)
      return (adapter_type, wrapper_type)
    return ('ParameterAdapter< %s >' % native_type, self._idl_type)

  def parameter_type(self):
    return '%s*' % self.native_type()

  def webcore_include(self):
    if self._idl_type == 'SVGNumber' or self._idl_type == 'SVGPoint':
      return None
    if self._idl_type.startswith('SVGPathSeg'):
      return self._idl_type.replace('Abs', '').replace('Rel', '')
    return self._idl_type

  def receiver(self):
    return 'receiver->'

  def conversion_include(self):
    return 'Dart%s' % self._idl_type

  def conversion_cast(self, expression):
    if self._conversion_template:
      return self._conversion_template % expression
    return expression

  def custom_to_dart(self):
    return self._custom_to_dart

class PrimitiveIDLTypeInfo(IDLTypeInfo):
  def __init__(self, idl_type, native_type=None, ref_counted=False,
               conversion_template=None,
               webcore_getter_name='getAttribute',
               webcore_setter_name='setAttribute'):
    super(PrimitiveIDLTypeInfo, self).__init__(idl_type,
        native_type=native_type, ref_counted=ref_counted,
        conversion_template=conversion_template)
    self._webcore_getter_name = webcore_getter_name
    self._webcore_setter_name = webcore_setter_name

  def parameter_adapter_info(self):
    native_type = self.native_type()
    if self._ref_counted:
      native_type = 'RefPtr< %s >' % native_type
    return ('ParameterAdapter< %s >' % native_type, None)

  def parameter_type(self):
    if self.native_type() == 'String':
      return 'const String&'
    return self.native_type()

  def conversion_include(self):
    return None

  def webcore_getter_name(self):
    return self._webcore_getter_name

  def webcore_setter_name(self):
    return self._webcore_setter_name

class SVGTearOffIDLTypeInfo(IDLTypeInfo):
  def __init__(self, idl_type, native_type='', ref_counted=True):
    super(SVGTearOffIDLTypeInfo, self).__init__(idl_type,
                                                native_type=native_type,
                                                ref_counted=ref_counted)

  def native_type(self):
    if self._native_type:
      return self._native_type
    tear_off_type = 'SVGPropertyTearOff'
    if self._idl_type.endswith('List'):
      tear_off_type = 'SVGListPropertyTearOff'
    return '%s<%s>' % (tear_off_type, self._idl_type)

  def receiver(self):
    if self._idl_type.endswith('List'):
      return 'receiver->'
    return 'receiver->propertyReference().'


_idl_type_registry = {
     # There is GC3Dboolean which is not a bool, but unsigned char for OpenGL compatibility.
    'boolean': PrimitiveIDLTypeInfo('boolean', native_type='bool',
                                    conversion_template='static_cast<bool>(%s)',
                                    webcore_getter_name='hasAttribute',
                                    webcore_setter_name='setBooleanAttribute'),
    # Some IDL's unsigned shorts/shorts are mapped to WebCore C++ enums, so we
    # use a static_cast<int> here not to provide overloads for all enums.
    'short': PrimitiveIDLTypeInfo('short', native_type='int', conversion_template='static_cast<int>(%s)'),
    'unsigned short': PrimitiveIDLTypeInfo('unsigned short', native_type='int', conversion_template='static_cast<int>(%s)'),
    'int': PrimitiveIDLTypeInfo('int'),
    'unsigned int': PrimitiveIDLTypeInfo('unsigned int', native_type='unsigned'),
    'long': PrimitiveIDLTypeInfo('long', native_type='int',
        webcore_getter_name='getIntegralAttribute',
        webcore_setter_name='setIntegralAttribute'),
    'unsigned long': PrimitiveIDLTypeInfo('unsigned long', native_type='unsigned',
        webcore_getter_name='getUnsignedIntegralAttribute',
        webcore_setter_name='setUnsignedIntegralAttribute'),
    'long long': PrimitiveIDLTypeInfo('long long'),
    'unsigned long long': PrimitiveIDLTypeInfo('unsigned long long'),
    'double': PrimitiveIDLTypeInfo('double'),

    'Date': PrimitiveIDLTypeInfo('Date',  native_type='double'),
    'DOMString': PrimitiveIDLTypeInfo('DOMString',  native_type='String'),
    'DOMTimeStamp': PrimitiveIDLTypeInfo('DOMTimeStamp'),
    'object': PrimitiveIDLTypeInfo('object',  native_type='ScriptValue'),
    'SerializedScriptValue': PrimitiveIDLTypeInfo('SerializedScriptValue', ref_counted=True),

    'DOMException': IDLTypeInfo('DOMCoreException'),
    'DOMWindow': IDLTypeInfo('DOMWindow', custom_to_dart=True),
    'Element': IDLTypeInfo('Element', custom_to_dart=True),
    'EventListener': IDLTypeInfo('EventListener', has_dart_wrapper=False),
    'EventTarget': IDLTypeInfo('EventTarget', has_dart_wrapper=False),
    'HTMLElement': IDLTypeInfo('HTMLElement', custom_to_dart=True),
    'MediaQueryListListener': IDLTypeInfo('MediaQueryListListener', has_dart_wrapper=False),
    'OptionsObject': IDLTypeInfo('OptionsObject', has_dart_wrapper=False),
    'SVGElement': IDLTypeInfo('SVGElement', custom_to_dart=True),

    'SVGAngle': SVGTearOffIDLTypeInfo('SVGAngle'),
    'SVGLength': SVGTearOffIDLTypeInfo('SVGLength'),
    'SVGLengthList': SVGTearOffIDLTypeInfo('SVGLengthList', ref_counted=False),
    'SVGMatrix': SVGTearOffIDLTypeInfo('SVGMatrix'),
    'SVGNumber': SVGTearOffIDLTypeInfo('SVGNumber', native_type='SVGPropertyTearOff<float>'),
    'SVGNumberList': SVGTearOffIDLTypeInfo('SVGNumberList', ref_counted=False),
    'SVGPathSegList': SVGTearOffIDLTypeInfo('SVGPathSegList', native_type='SVGPathSegListPropertyTearOff', ref_counted=False),
    'SVGPoint': SVGTearOffIDLTypeInfo('SVGPoint', native_type='SVGPropertyTearOff<FloatPoint>'),
    'SVGPointList': SVGTearOffIDLTypeInfo('SVGPointList', ref_counted=False),
    'SVGPreserveAspectRatio': SVGTearOffIDLTypeInfo('SVGPreserveAspectRatio'),
    'SVGRect': SVGTearOffIDLTypeInfo('SVGRect', native_type='SVGPropertyTearOff<FloatRect>'),
    'SVGStringList': SVGTearOffIDLTypeInfo('SVGStringList', native_type='SVGStaticListPropertyTearOff<SVGStringList>', ref_counted=False),
    'SVGTransform': SVGTearOffIDLTypeInfo('SVGTransform'),
    'SVGTransformList': SVGTearOffIDLTypeInfo('SVGTransformList', native_type='SVGTransformListPropertyTearOff', ref_counted=False)
}

original_idl_types = {
}

def GetIDLTypeInfo(idl_type):
  idl_type_name = original_idl_types.get(idl_type, idl_type.id)
  return GetIDLTypeInfoByName(idl_type_name)

def GetIDLTypeInfoByName(idl_type_name):
  return _idl_type_registry.get(idl_type_name, IDLTypeInfo(idl_type_name))
