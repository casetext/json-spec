"""
    jsontools.schema.validators.primitives
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

"""

from __future__ import absolute_import, print_function, unicode_literals

__all__ = ['ArrayValidator', 'BooleanValidator', 'IntegerValidator',
           'NullValidator', 'NumberValidator', 'ObjectValidator',
           'StringValidator']

import itertools
import logging
import os.path
import re

from copy import deepcopy
from six import integer_types, string_types

from .bases import factory, Validator
from jsontools.exceptions import CompilationError, ValidationError

logger = logging.getLogger(__name__)


class ArrayValidator(Validator):
    type = 'array'

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.items = attrs.pop('items', {})
        self.additionalItems = attrs.pop('additionalItems', False)
        self.maxItems = attrs.pop('maxItems', None)
        self.minItems = attrs.pop('minItems', 0)
        self.uniqueItems = attrs.pop('uniqueItems', None)

    @property
    def items(self):
        obj = self._items
        if isinstance(obj, Validator):
            return itertools.cycle([obj])
        if not obj:
            return []
        return obj

    @items.setter
    def items(self, obj):
        self._items = obj

    @property
    def additionalItems(self):
        obj = self._additionalItems
        if isinstance(obj, Validator):
            return itertools.cycle([obj])
        elif not obj:
            return []
        return obj

    @additionalItems.setter
    def additionalItems(self, obj):
        self._additionalItems = obj

    @classmethod
    def compile(cls, schema, uri):
        attrs = super().compile(schema, uri)

        for name in ('items', 'additionalItems'):
            if name not in schema:
                continue

            attr = schema[name]
            sub_uri = os.path.join(uri, name)
            if isinstance(attr, list):
                # each value must be a json schema
                attr = [factory(attr, sub_uri) for element in attr]
            elif isinstance(attr, dict):
                # value must be a json schema
                attr = factory(attr, sub_uri)
            elif not isinstance(attr, bool):
                # should be a boolean
                raise CompilationError('wrong type for {}'.format(name), schema)  # noqa

            attrs[name] = attr

        for name in ('maxItems', 'minItems'):
            if name not in schema:
                continue
            attr = schema[name]
            if not isinstance(attr, int):
                # should be a boolean
                raise CompilationError('{} must be a integer'.format(name), schema)  # noqa
            if attr < 0:
                # should be a boolean
                raise CompilationError('{} must be greater than 0'.format(name), schema)  # noqa
            attrs[name] = attr

        if 'uniqueItems' in schema:
            attr = schema['uniqueItems']
            if not isinstance(attr, bool):
                raise CompilationError('{} must be a bool'.format(name), schema)  # noqa
            attrs[name] = attr

        return cls(**attrs)

    def validate(self, obj):
        self.validate_type(obj)
        self.validate_count(obj)
        self.validate_unique(obj)
        self.validate_items(obj)
        return super().validate(obj)

    def validate_type(self, obj):
        if not isinstance(obj, list):
            raise ValidationError('object must be a list')

    def validate_items(self, obj):
        if self._items == {}:
            # validation of the instance always succeeds
            # regardless of the value of "additionalItems"
            return
        if self._additionalItems in (True, {}):
            # validation of the instance always succeeds
            return

        schemas = itertools.chain(self.items, self.additionalItems)
        iteration = 0
        errors = []
        for sub, schema in zip(obj, schemas):
            iteration += 1
            try:
                if schema == {}:
                    continue
                else:
                    schema.validate(sub)
            except ValidationError as error:
                errors.append(error)
        if errors:
            raise ValidationError(errors)

        if iteration < len(obj):
            raise ValidationError('object has too much elements')

    def validate_count(self, obj):
        l = len(obj)
        if self.minItems and l < self.minItems:
            raise ValidationError('object must have at least '
                                  '{} elements'.format(self.minItems))
        if self.maxItems and l > self.maxItems:
            raise ValidationError('object must have less than '
                                  '{} elements'.format(self.maxItems))

    def validate_unique(self, obj):
        if self.uniqueItems and len(set(obj)) != len(obj):
            raise ValidationError('items must be unique')


class ObjectValidator(Validator):
    type = 'object'

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.properties = attrs.pop('properties', {})
        self.patternProperties = attrs.pop('patternProperties', {})
        self.additionalProperties = attrs.pop('additionalProperties', {})
        self.maxProperties = attrs.pop('maxProperties', None)
        self.minProperties = attrs.pop('minProperties', None)
        self.required = attrs.pop('required', [])

    @classmethod
    def compile(cls, schema, uri):
        attrs = super().compile(schema, uri)

        for name in ('maxProperties', 'minProperties'):
            if name in schema:
                attr = schema[name]
                attrs[name] = attr

        for name in ('properties', 'patternProperties'):
            if name in schema:
                if not isinstance(schema[name], dict):
                    raise CompilationError('{} must be a dict'.format(name),
                                           schema)
                attr = {}
                for subname, subschema in schema[name].items():
                    attr[subname] = factory(subschema, os.path.join(uri, name))
                attrs[name] = attr

        for name in ('maxProperties', 'minProperties'):
            if name in schema:
                attr = schema[name]
                if not isinstance(attr, integer_types):
                    raise CompilationError('{} must be an integer'.format(name),
                                           schema)
                if attr < 0:
                    raise CompilationError('{} must be greater than 0'.format(name),
                                           schema)
                attrs[name] = attr

        if 'additionalProperties' in schema:
            attr = schema['additionalProperties']
            if isinstance(attr, dict):
                attr = factory(attr, os.path.join(uri, name))
            elif attr is True:
                attr = factory({}, os.path.join(uri, name))
            elif not isinstance(schema['additionalProperties'], bool):
                raise CompilationError('additionalProperties must be '
                                       'a dict or a bool', schema)
            attrs['additionalProperties'] = attr

        if 'required' in schema:
            attrs['required'] = schema['required'][:]

        return cls(**attrs)

    def validate(self, obj):
        self.validate_type(obj)
        self.validate_required(obj)
        obj = self.validate_properties(obj)
        return super().validate(obj)

    def validate_type(self, obj):
        if not isinstance(obj, dict):
            raise ValidationError('object must be a dict')

    def validate_required(self, obj):
        for member in self.required:
            if member not in obj:
                raise ValidationError('{!r} is required'.format(member))

    def validate_properties(self, obj):
        l = len(obj)
        if isinstance(self.maxProperties, integer_types) and l > self.maxProperties:
            raise ValidationError('too much properties, max {}'.format(self.maxProperties))
        if isinstance(self.minProperties, integer_types) and l < self.minProperties:
            raise ValidationError('too few properties, min {}'.format(self.minProperties))

        obj = deepcopy(obj)
        errors, missing = {}, set(obj.keys())
        for member, schema in self.properties.items():
            if member in obj:
                try:
                    schema.validate(obj[member])
                    missing.discard(member)
                except ValidationError as error:
                    errors[member] = error
            elif schema.has_default():
                obj[member] = deepcopy(schema.default)
        if errors:
            raise ValidationError(errors)
        for pattern, schema in self.patternProperties.items():
            regex = re.compile(pattern)
            for member, value in obj.items():
                if regex.match(member):
                    try:
                        schema.validate(value)
                        missing.discard(member)
                    except ValidationError as error:
                        errors[member] = error
        if errors:
            raise ValidationError(errors)

        if missing:
            if self.additionalProperties in ({}, True):
                missing.clear()
            elif self.additionalProperties:
                schema = self.additionalProperties
                for member in missing:
                    try:
                        obj[member] = schema.validate(obj[member])
                        missing.discard(member)
                    except ValidationError as error:
                        errors[member] = error
        if errors:
            raise ValidationError(errors)

        if missing:
            raise ValidationError('missing definitions for {}'.format(missing))

        return obj


class BooleanValidator(Validator):
    type = 'boolean'

    def validate_type(self, obj):
        if obj not in (True, False):
            raise ValidationError('obj must be a boolean', obj)


class NumberValidator(Validator):
    type = 'number'

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.minimum = attrs.pop('minimum', None)
        self.maximum = attrs.pop('maximum', None)
        self.exclusiveMinimum = attrs.pop('exclusiveMinimum', False)
        self.exclusiveMaximum = attrs.pop('exclusiveMaximum', False)
        self.multipleOf = attrs.pop('multipleOf', None)

    @classmethod
    def compile(cls, schema, uri):
        attrs = super().compile(schema, uri)

        if 'multipleOf' in schema:
            attr = schema['multipleOf']
            if not isinstance(attr, (int, float)):
                raise CompilationError('multipleOf must be a number', schema)
            if attr < 0:
                raise CompilationError('multipleOf must be greater than 0',
                                       schema)
            attrs['multipleOf'] = attr

        if 'minimum' in schema:
            attr = schema['minimum']
            if not isinstance(attr, (int, float)):
                raise CompilationError('minimum must be a number', schema)
            attrs['minimum'] = attr
        if 'exclusiveMinimum' in schema:
            attr = schema['exclusiveMinimum']
            if not isinstance(attr, bool):
                raise CompilationError('exclusiveMinimum must be a boolean',
                                       schema)
            if 'minimum' not in schema:
                raise CompilationError('exclusiveMinimum reclame maximum',
                                       schema)
            attrs['exclusiveMinimum'] = attr

        if 'maximum' in schema:
            attr = schema['maximum']
            if not isinstance(attr, (int, float)):
                raise CompilationError('maximum must be a number', schema)
            attrs['maximum'] = attr
        if 'exclusiveMaximum' in schema:
            attr = schema['exclusiveMaximum']
            if not isinstance(attr, bool):
                raise CompilationError('exclusiveMaximum must be a boolean',
                                       schema)
            if 'maximum' not in schema:
                raise CompilationError('exclusiveMaximum reclame maximum',
                                       schema)
            attrs['exclusiveMaximum'] = attr

        return cls(**attrs)

    def validate(self, obj):
        self.validate_type(obj)
        self.validate_minimum(obj)
        self.validate_maximum(obj)
        self.validate_multiple(obj)
        return super().validate(obj)

    def validate_type(self, obj):
        if not isinstance(obj, (int, integer_types, float)):
            raise ValidationError('object must be a number')
        if isinstance(obj, bool):
            raise ValidationError('obj must be an int', obj)

    def validate_minimum(self, obj):
        if self.minimum is not None:
            if not obj >= self.minimum:
                raise ValidationError('object must be greater '
                                      'than {}'.format(self.minimum))
            if self.exclusiveMinimum and obj == self.minimum:
                raise ValidationError('object must be greater '
                                      'than {}'.format(self.minimum))

    def validate_maximum(self, obj):
        if self.maximum is not None:
            if not obj <= self.maximum:
                raise ValidationError('object must be lesser '
                                      'than {}'.format(self.maximum))
            if self.exclusiveMaximum and obj == self.maximum:
                raise ValidationError('object must be lesser '
                                      'than {}'.format(self.maximum))

    def validate_multiple(self, obj):
        if self.multipleOf and not obj % self.multipleOf == 0:
            raise ValidationError('object must be a multiple '
                                  'of {}'.format(self.multipleOf))


class IntegerValidator(NumberValidator):
    type = 'integer'

    def validate_type(self, obj):
        if not isinstance(obj, integer_types):
            raise ValidationError('obj must be an int', obj)
        if isinstance(obj, bool):
            raise ValidationError('obj must be an int', obj)


class StringValidator(Validator):
    type = 'string'

    def __init__(self, **attrs):
        """
        todo implement format validator.
        """
        super().__init__(**attrs)
        self.maxLength = attrs.pop('maxLength', None)
        self.minLength = attrs.pop('minLength', None)
        self.pattern = attrs.pop('pattern', None)

    @classmethod
    def compile(cls, schema, uri):
        attrs = super().compile(schema, uri)

        if 'maxLength' in schema:
            attr = 'maxLength'
            if not isinstance(attr, int):
                raise CompilationError('maxLength must be an integer', schema)
            if attr < 0:
                raise CompilationError('maxLength must be equal '
                                       'or greater than 0', schema)
            attrs['maxLength'] = attr

        if 'minLength' in schema:
            attr = 'minLength'
            if not isinstance(attr, int):
                raise CompilationError('minLength must be an integer', schema)
            if attr < 0:
                raise CompilationError('minLength must be equal '
                                       'or greater than 0', schema)
            attrs['minLength'] = attr

        if 'pattern' in schema:
            attr = 'pattern'
            if not isinstance(attr, str):
                raise CompilationError('pattern must be an integer', schema)
            attrs['pattern'] = attr

        return cls(**attrs)

    def validate(self, obj):
        self.validate_type(obj)
        self.validate_length(obj)
        self.validate_pattern(obj)
        return super().validate(obj)

    def validate_type(self, obj):
        if not isinstance(obj, string_types):
            raise ValidationError('obj must be a string', obj)

    def validate_length(self, obj):
        l = len(obj)
        if self.minLength and l < self.minLength:
            raise ValidationError('length of obj must be greater or equal'
                                  ' than {}'.format(self.minLength))
        if self.maxLength and l > self.maxLength:
            raise ValidationError('length of obj must be lesser or equal'
                                  ' than {}'.format(self.minLength))

    def validate_pattern(self, obj):
        if self.pattern and not self.regex.match(obj):
            raise ValidationError('obj does not validate '
                                  '{!r} pattern'.format(self.pattern))

    @property
    def regex(self):
        if not hasattr(self, '_regex'):
            setattr(self, '_regex', re.compile(self.pattern))
        return self._regex


class NullValidator(Validator):
    type = 'null'

    def validate_type(self, obj):
        if obj is not None:
            raise ValidationError('obj must be null', obj)
