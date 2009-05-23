# Copyright 2009, Peter A. Bigot
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain a
# copy of the License at:
#
#            http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Helper classes that maintain the content model of XMLSchema in the binding
classes.

AttributeUse and ElementUse record information associated with a binding
class, for example the types of values, the original XML QName or NCName, and
the Python field in which the values are stored.

ContentModelTransition, ContentModelState, and ContentModel are used to store
a deterministic finite automaton which is used to translate DOM nodes into
values stored in an instance corresponding to a complex type definition.

ModelGroupAllAlternative and ModelGroupAll represent special nodes in the DFA
that support a model group with compositor "all" in a way that does not result
in an exponential state explosion in the DFA.

Particle, ModelGroup, and Wildcard are used to encode an earlier
representation of the content model, now used only for generating DOM
instances from bindings (as opposed to the other direction handled by
ContentModel).  Wildcard is also used in the DFA-based content model.
"""

import pyxb
import pyxb.Namespace
import basis

import xml.dom

class AttributeUse (pyxb.cscRoot):
    """A helper class that encapsulates everything we need to know
    about the way an attribute is used within a binding class.

    Attributes are stored as pairs of (provided, value), where provided is a
    boolean indicating whether a value for the attribute was provided by the
    DOM node, and value is an instance of the attribute datatype.  The
    provided flag is used to determine whether an XML attribute should be
    added to a created DOM node when generating the XML corresponding to a
    binding instance.
    """

    __tag = None       # Unicode XML tag @todo not including namespace
    __pythonField = None # Identifier used for this attribute within the owning class
    __valueAttributeName = None # Private attribute used in instances to hold the attribute value
    __dataType = None  # PST datatype
    __unicodeDefault = None     # Default value as a unicode string, or None
    __defaultValue = None       # Default value as an instance of datatype, or None
    __fixed = False             # If True, value cannot be changed
    __required = False          # If True, attribute must appear
    __prohibited = False        # If True, attribute must not appear

    def __init__ (self, tag, python_field, value_attribute_name, data_type, unicode_default=None, fixed=False, required=False, prohibited=False):
        self.__tag = tag
        self.__pythonField = python_field
        self.__valueAttributeName = value_attribute_name
        self.__dataType = data_type
        self.__unicodeDefault = unicode_default
        if self.__unicodeDefault is not None:
            self.__defaultValue = self.__dataType(self.__unicodeDefault)
        self.__fixed = fixed
        self.__required = required
        self.__prohibited = prohibited

    def tag (self):
        """Unicode tag for the attribute in its element"""
        return self.__tag
    
    def prohibited (self): return self.__prohibited
    def required (self): return self.__required

    def pythonField (self):
        """Tag used within Python code for the attribute"""
        return self.__pythonField

    def __getValue (self, ctd_instance):
        return getattr(ctd_instance, self.__valueAttributeName, (False, None))

    def __getProvided (self, ctd_instance):
        return self.__getValue(ctd_instance)[0]

    def value (self, ctd_instance):
        """Get the value of the attribute."""
        return self.__getValue(ctd_instance)[1]

    def __setValue (self, ctd_instance, new_value, provided):
        return setattr(ctd_instance, self.__valueAttributeName, (provided, new_value))

    def reset (self, ctd_instance):
        self.__setValue(ctd_instance, self.__defaultValue, False)

    def setFromDOM (self, ctd_instance, node):
        """Set the value of the attribute in the given instance from the
        corresponding attribute of the DOM Element node.

        :param ctd_instance: instance of ComplexTypeDefinition to which attribute belongs
        :param node: DOM node from which attribute value should be taken
        :raise ProhibitedAttributeError: an attempt was made to set a prohibited attribute
        :raise MissingAttributeError: a required attribute did not receive a value
        """
        unicode_value = self.__unicodeDefault
        provided = False
        assert isinstance(node, xml.dom.Node)
        if node.hasAttribute(self.__tag):
            if self.__prohibited:
                raise pyxb.ProhibitedAttributeError('Prohibited attribute %s found' % (self.__tag,))
            unicode_value = node.getAttribute(self.__tag)
            provided = True
        else:
            if self.__required:
                raise pyxb.MissingAttributeError('Required attribute %s not found' % (self.__tag,))
        if unicode_value is None:
            # Must be optional and absent
            self.__setValue(ctd_instance, None, False)
        else:
            new_value = self.__dataType(unicode_value)
            if self.__fixed and (new_value != self.__defaultValue):
                raise pyxb.AttributeChangeError('Attempt to change value of fixed attribute %s (%s to %s)' % (self.__tag, repr(self.__defaultValue), repr(new_value)))
            # NB: Do not set provided here; this may be the default
            self.__setValue(ctd_instance, new_value, provided)
        return self

    def addDOMAttribute (self, ctd_instance, element):
        """If this attribute as been set, add the corresponding attribute to the DOM element."""
        ( provided, value ) = self.__getValue(ctd_instance)
        if provided:
            assert value is not None
            element.setAttribute(self.__tag, value.xsdLiteral())
        return self

    def setValue (self, ctd_instance, new_value):
        """Set the value of the attribute.

        This validates the value against the data type."""
        assert new_value is not None
        if not isinstance(new_value, self.__dataType):
            new_value = self.__dataType(new_value)
        if self.__fixed and (new_value != self.__defaultValue):
            raise pyxb.AttributeChangeError('Attempt to change value of fixed attribute %s' % (self.__tag,))
        self.__setValue(ctd_instance, new_value, True)
        return new_value

class ElementUse (pyxb.cscRoot):
    """Aggregate the information relevant to an element of a complex type.

    This includes the original tag name, the spelling of the corresponding
    object in Python, an indicator of whether multiple instances might be
    associated with the field, and a list of types for legal values of the
    field."""

    def tag (self):
        """The Unicode XML NCName of the element."""
        return self.__tag
    __tag = None

    def pythonField (self):
        """The string name of the binding class field used to hold the element
        values.

        This is the user-visible name, and excepting namespace disambiguation
        will be equal to the tag."""
        return self.__pythonField
    __pythonField = None

    # The dictionary key used to identify the value of the element.  The value
    # is the same as that used for private member variables in the binding
    # class within which the element declaration occurred.
    __valueElementName = None

    def validElements (self):
        """A list of binding classes that express the permissible types of
        element instances for this use."""
        return self.__validElements
    __validElements = None

    def isPlural (self):
        """True iff the content model indicates that more than one element
        can legitimately belong to this use.

        This includes elements in particles with maxOccurs greater than one,
        and when multiple elements with the same NCName are declared in the
        same type."""
        return self.__isPlural
    __isPlural = False

    # If not None, this specifies an ElementUse in a binding class for
    # which this element use is a restriction.  That element use is
    # what is used to store the corresponding values, after validating
    # them against validElements at this level.
    __parentUse = None

    def __init__ (self, tag, python_field, value_element_name, is_plural, default=None, valid_elements=[]):
        self.__tag = tag
        self.__pythonField = python_field
        self.__valueElementName = value_element_name
        self.__isPlural = is_plural
        self.__validElements = valid_elements

    def _setValidElements (self, valid_elements):
        self.__validElements = valid_elements

    def defaultValue (self):
        if self.isPlural():
            return []
        return None

    def clearGenerationMarkers (self, ctd_instance):
        value = self.value(ctd_instance)
        if not self.isPlural():
            if value is None:
                return
            value = [ value ]
        for v in value:
            assert v is not None
            v.__generated = False

    def nextValueToGenerate (self, ctd_instance):
        value = self.value(ctd_instance)
        if not self.isPlural():
            if value is None:
                raise pyxb.DOMGenerationError('Optional %s value is not available' % (self.pythonField(),))
            value = [ value ]
        for v in value:
            if not v.__generated:
                v.__generated = True
                return v
        raise pyxb.DOMGenerationError('No %s values remain to be generated' % (self.pythonField(),))

    def hasUngeneratedValues (self, ctd_instance):
        value = self.value(ctd_instance)
        if not self.isPlural():
            if value is None:
                return False
            value = [ value ]
        for v in value:
            if not v.__generated:
                return True
        return False

    def value (self, ctd_instance):
        return getattr(ctd_instance, self.__valueElementName, self.defaultValue())

    def reset (self, ctd_instance):
        setattr(ctd_instance, self.__valueElementName, self.defaultValue())
        return self

    def __setValue (self, ctd_instance, value):
        #print 'Set value of %s to %s' % (self.tag(), value)
        if self.isPlural():
            values = self.value(ctd_instance)
            values.append(value)
            return values
        return setattr(ctd_instance, self.__valueElementName, value)

    # @todo Distinguish based on plurality
    def setValue (self, ctd_instance, value):
        """Set the value of this element in the given instance."""
        if value is None:
            return self.reset(ctd_instance)
        assert self.__validElements is not None
        for dt in self.__validElements:
            if isinstance(value, dt):
                self.__setValue(ctd_instance, value)
                ctd_instance._addContent(value)
                return self
        for dt in self.__validElements:
            # Ignore elements that we just can't convert to, but pass through
            # exceptions when a constraint is violated.
            try:
                iv = dt(value, validate_constraints=False)
            except pyxb.BadTypeValueError, e:
                continue
            assert isinstance(iv, basis._Binding_mixin)
            if iv._IsSimpleTypeContent():
                iv.xsdConstraintsOK()
            self.__setValue(ctd_instance, iv)
            ctd_instance._addContent(iv)
            return self
        raise pyxb.BadTypeValueError('Cannot assign value of type %s to field %s: legal types %s' % (type(value), self.tag(), ' '.join([str(_dt) for _dt in self.__validElements])))

class ContentModelTransition (pyxb.cscRoot):
    """Represents a transition in the content model DFA.

    If the next object in the DOM model conforms to the specified term, it is
    consumed and the specified next state is entered."""

    def term (self):
        """The matching term for this transition to succeed."""
        return self.__term
    __term = None

    def nextState (self):
        """The next state in the DFA"""
        return self.__nextState
    __nextState = None

    # The ElementUse instance used to store a successful match in the
    # complex type definition instance.
    __elementUse = None

    # Types of transition that can be taken, in order of preferred match
    TT_element = 0x01           #<<< The transition is on an element
    TT_modelGroupAll = 0x02     #<<< The transition is on an ALL model group
    TT_wildcard = 0x03          #<<< The transition is on a wildcard

    # What type of term this transition covers
    __termType = None

    def __init__ (self, term, next_state, element_use=None):
        """Create a transition to a new state upon receipt of a term,
        storing the successful match using the provided ElementUse."""
        self.__term = term
        self.__nextState = next_state
        assert self.__nextState is not None
        self.__elementUse = element_use
        if isinstance(self.__term, type) and issubclass(self.__term, basis.element):
            self.__termType = self.TT_element
        elif isinstance(self.__term, ModelGroupAll):            
            self.__termType = self.TT_modelGroupAll
        elif isinstance(self.__term, Wildcard):
            self.__termType = self.TT_wildcard
        else:
            raise pyxb.LogicError('Unexpected transition term %s' % (self.__term,))

    def __cmp__ (self, other):
        """Sort transitions so elements precede model groups precede
        wildcards.  Also sort within each subsequence."""
        rv = cmp(self.__termType, other.__termType)
        if 0 == rv:
            rv = cmp(self.__term, other.__term)
        return rv

    def attemptTransition (self, ctd_instance, node_list, store):
        """Attempt to make the appropriate transition.

        If something goes wrong, a BadDocumentError will be propagated through
        this call, and node_list will remain unchanged.  If everything works,
        the prefix of the node_list that matches the transition will have been
        stripped away, and if the store parameter is True, the resulting
        binding instances will be stored in the proper location of
        ctd_instance.
        """

        if self.TT_element == self.__termType:
            if 0 == len(node_list):
                raise pyxb.MissingContentError('No DOM nodes for reduction of %s' % (self.__term,))
            #print 'Element reduction attempt attempt for %s' % (self.__term,)
            element = self.__term.CreateFromDOM(node_list[0])
            node_list.pop(0)
            if store:
                self.__elementUse.setValue(ctd_instance, element)
        elif self.TT_modelGroupAll == self.__termType:
            #print 'All model group reduction attempt'
            self.__term.matchAlternatives(ctd_instance, node_list, store)
        elif self.TT_wildcard == self.__termType:
            #print 'Wildcard reduction attempt'
            if 0 == len(node_list):
                raise pyxb.MissingContentError()
            if not self.__term.matchesNode(ctd_instance, node_list[0]):
                raise pyxb.UnexpectedContentError(node_list[0])
            node = node_list.pop(0)
            # See if we can convert from DOM into a Python instance.
            # If not, we'll go ahead and store the DOM node.
            try:
                ns = pyxb.Namespace.NamespaceForURI(node.namespaceURI, create_if_missing=True)
                if ns.module() is not None:
                    node = ns.module().CreateFromDOM(node)
                elif ns.modulePath() is not None:
                    print 'Importing %s' % (ns.modulePath(),)
                    mod = __import__(ns.modulePath())
                    for c in ns.modulePath().split('.')[1:]:
                        mod = getattr(mod, c)
                    node = mod.CreateFromDOM(node)
                elif pyxb.Namespace.XMLSchema == ns:
                    print 'Need to dynamically create schema'
            except Exception, e:
                print 'WARNING: Unable to convert wildcard %s %s to Python instance: %s' % (node.namespaceURI, node.localName, e)
            if store:
                ctd_instance.wildcardElements().append(node)
        else:
            raise pyxb.LogicError('Unexpected transition term %s' % (self.__term,))

class ContentModelState (pyxb.cscRoot):
    """Represents a state in a ContentModel DFA.

    The state identifier is an integer.  State 1 is the starting state of the
    DFA.  A flag indicates whether the state is a legitimate final state for
    the DFA.  The transitions are an ordered sequence of
    ContentModelTransition instances."""

    # Integer
    __state = None
    # Sequence of ContentModelTransition instances
    __transitions = None

    def isFinal (self):
        """If True, this state can successfully complete the element
        reduction."""
        return self.__isFinal
    __isFinal = None

    def __init__ (self, state, is_final, transitions):
        self.__state = state
        self.__isFinal = is_final
        self.__transitions = transitions
        self.__transitions.sort()

    def evaluateContent (self, ctd_instance, node_list, store):
        """Determine where to go from this state.

        If a transition matches, the consumed prefix of node_list has been
        stripped, the resulting data stored in ctd_instance if store is True,
        and the next state is returned.

        If no transition can be made, and this state is a final state for the
        DFA, the value None is returned.

        :param ctd_instance: The binding instance holding the content
        :param node_list: in/out list of DOM nodes that comprise instance content
        :param store: whether this actually consumes or just tests
        :raise pyxb.UnrecognizedContentError: trailing material that does not match content model
        :raise pyxb.MissingContentError: content model requires additional data
        """

        for transition in self.__transitions:
            # @todo check nodeName against element
            try:
                #print 'Attempting transition at %s' % (transition.term(),)
                transition.attemptTransition(ctd_instance, node_list, store)
                #print 'Transition succeeded with %s' % (transition.term(),)

                return transition.nextState()
            except pyxb.StructuralBadDocumentError, e:
                #print 'Transition failed with %s: %s' % (transition.term(), e)
                pass
        if self.isFinal():
            return None
        if 0 < len(node_list):
            raise pyxb.UnrecognizedContentError(node_list[0])
        raise pyxb.MissingContentError()

class ContentModel (pyxb.cscRoot):
    """The ContentModel is a deterministic finite state automaton which can be
    traversed using a sequence of DOM nodes which are matched on transitions
    against the legal content model of a complex type."""

    # Map from integers to ContentModelState instances
    __stateMap = None

    def __init__ (self, state_map=None):
        self.__stateMap = state_map

    def interprete (self, ctd_instance, node_list, store=True):
        """Attempt to match the content model against the node_list.

        When a state has been reached from which no transition is possible,
        this method returns (if the end state is a final state), or throws a
        MissingContentError.  There may be material remaining on the
        node_list; it is up to the caller to determine whether this is
        acceptable."""
        state = 1
        while state is not None:
            node_list = ctd_instance._stripMixedContent(node_list)
            state = self.__stateMap[state].evaluateContent(ctd_instance, node_list, store)
        node_list = ctd_instance._stripMixedContent(node_list)
        if state is not None:
            raise pyxb.MissingContentError()


class ModelGroupAllAlternative (pyxb.cscRoot):
    """Represents a single alternative in an "all" model group."""

    def contentModel (self):
        """The content model definition for the alternative."""
        return self.__contentModel
    __contentModel = None

    def required (self):
        """True iff this alternative must be present (min_occurs=1)"""
        return self.__required
    __required = None

    def __init__ (self, content_model, required):
        #print '%s created MGA alternative model %s required %s' % (self, content_model, required)
        self.__contentModel = content_model
        self.__required = required


class ModelGroupAll (pyxb.cscRoot):
    """Content model class that represents a ModelGroup with an "all"
    compositor."""

    __alternatives = None

    def __init__ (self, alternatives):
        self.__alternatives = alternatives

    def matchAlternatives (self, ctd_instance, node_list, store=True):
        """Match the node_list against the alternatives in this model group.

        This method creates a set holding all the alternatives, then walks the
        node list attempting to match against the content model of each
        alternative in turn.  The store flag is cleared during this process,
        so that the ctd_instance fields are not updated but the node_list
        values are removed.  Upon successful recognition of all required
        alternatives, the node_list is restored and the content model matching
        repeated with store set to update the ctd_instance values.

        @todo: This method complicates things because it won't commit to the
        consumptions until the whole model is matched.  This step is taken
        because the match operation corresponds to a single transition in the
        DFA, and we are not sure whether the transition will be successful.
        Almost certainly this is not necessary, since the UPA should require
        that when a prefix of the node list from matches this transition, the
        whole transition is valid.  On the other hand, that assumes that we're
        getting valid documents.
        """

        # Save the incoming node list so we can re-execute the
        # alternatives if they match.
        saved_node_list = node_list[:]

        alternatives = set(self.__alternatives)
        match_order = []
        found_match = True
        #print 'Starting to match ALL with %d alternatives and %d nodes, store is %s' % (len(alternatives), len(node_list), store)

        # The alternatives can match in arbitrary order, so repeatedly try
        # them until they're all gone or no match can be found.
        while (0 < len(alternatives)) and found_match:
            found_match = False
            #if 0 < len(node_list):
            #    print 'Next up: %s' % (node_list[0],)
            #else:
            #    print 'Next up: nothing'
            for alt in alternatives:
                try:
                    #print 'Trying alternative %s, required %s: %s' % (alt, alt.required(), alt.contentModel())
                    node_count = len(node_list)
                    alt.contentModel().interprete(ctd_instance, node_list, store=False)
                    #print 'Completed interpret with %d nodes out of %d left' % (len(node_list), node_count)
                    if len(node_list) < node_count:
                        #print 'Succeeded with alternative %s' % (alt,)
                        match_order.append(alt)
                        alternatives.remove(alt)
                        found_match = True
                        break
                except pyxb.BadDocumentError, e:
                    #print 'Failed with alternative %s: %s' % (alt, type(e))
                    pass
        # If there's a required alternative that wasn't matched, raise
        # an error
        #print 'Checking %d remaining alternatives for required' % (len(alternatives),)
        if 0 < len(alternatives):
            for alt in alternatives:
                #print 'Alternative %s required %s' % (alt, alt.required())
                if alt.required():
                    raise pyxb.MissingContentError(alt)
        # If this isn't a dry run, re-execute the alternatives in the
        # successful order.
        if store:
            #print 'Storing by matching %d alternatives in order' % (len(match_order),)
            for alt in match_order:
                #print 'Re-executing alternative %s with %d nodes left' % (alt, len(saved_node_list),)
                alt.contentModel().interprete(ctd_instance, saved_node_list)
            assert saved_node_list == node_list

class Particle (pyxb.cscRoot):
    """Record defining the structure and number of an XML object.
    This is a min and max count associated with a
    ModelGroup, ElementDeclaration, or Wildcard."""
    # The minimum number of times the term may appear.
    __minOccurs = 1
    def minOccurs (self):
        """The minimum number of times the term may appear.

        Defaults to 1."""
        return self.__minOccurs

    # Upper limit on number of times the term may appear.
    __maxOccurs = 1
    def maxOccurs (self):
        """Upper limit on number of times the term may appear.

        If None, the term may appear any number of times; otherwise,
        this is an integral value indicating the maximum number of times
        the term may appear.  The default value is 1; the value, unless
        None, must always be at least minOccurs().
        """
        return self.__maxOccurs

    # A reference to a ModelGroup, WildCard, or ElementDeclaration
    __term = None
    def term (self):
        """A reference to a ModelGroup, Wildcard, or ElementDeclaration."""
        return self.__term

    def isPlural (self):
        """Return true iff the term might appear multiple times."""
        if (self.maxOccurs() is None) or 1 < self.maxOccurs():
            return True
        return self.term().isPlural()

    def __init__ (self, min_occurs, max_occurs, term):
        self.__minOccurs = min_occurs
        self.__maxOccurs = max_occurs
        self.__term = term

    def extendDOMFromContent (self, dom_support, element, ctd_instance):
        """Add DOM constructs corresponding to data from a binding instance.

        :param dom_support: A pyxb.utils.domutils.BindingDOMSupport instance
        :param element: A DOM Element node into which binding values are written
        :param ctd_instance: A binding instance holding values
        """

        assert isinstance(dom_support, pyxb.utils.domutils.BindingDOMSupport)
        document = dom_support.document()
        rep = 0
        assert isinstance(ctd_instance, basis.complexTypeDefinition)
        while ((self.maxOccurs() is None) or (rep < self.maxOccurs())):
            try:
                if isinstance(self.term(), ModelGroup):
                    self.term().extendDOMFromContent(dom_support, element, ctd_instance)
                elif isinstance(self.term(), type) and issubclass(self.term(), basis.element):
                    eu = ctd_instance._UseForElement(self.term())
                    assert eu is not None
                    value = eu.nextValueToGenerate(ctd_instance)
                    value.toDOM(dom_support, element)
                elif isinstance(self.term(), Wildcard):
                    print 'Generation ignoring wildcard'
                    # @todo handle generation of wildcards
                    break
                else:
                    raise pyxb.IncompleteImplementationError('Particle.extendDOMFromContent: No support for term type %s' % (self.term(),))
            except pyxb.IncompleteImplementationError, e:
                raise
            except pyxb.DOMGenerationError, e:
                break
            except Exception, e:
                #print 'Caught extending DOM from term %s: %s' % (self.term(), e)
                raise
            rep += 1
        if rep < self.minOccurs():
            raise pyxb.DOMGenerationError('Expected at least %d instances of %s, got only %d' % (self.minOccurs(), self.term(), rep))

class ModelGroup (pyxb.cscRoot):
    """Record the structure of a model group.

    This is used when interpreting a DOM document fragment, to be sure
    the correct binding structure is used to extract the contents of
    each element.  It almost does something like validation, as a side
    effect."""

    C_INVALID = 0
    C_ALL = 0x01
    C_CHOICE = 0x02
    C_SEQUENCE = 0x03

    # One of the C_* values above.  Set at construction time from the
    # keyword parameter "compositor".
    __compositor = C_INVALID
    def compositor (self):
        return self.__compositor

    # A list of _Particle instances.  Set at construction time from
    # the keyword parameter "particles".  May be sorted; see
    # _setContent.
    __particles = None
    def particles (self):
        return self.__particles

    def _setContent (self, compositor, particles):
        self.__compositor = compositor
        self.__particles = particles

    def __init__ (self, compositor=C_INVALID, particles=None):
        self._setContent(compositor, particles)

    def __extendDOMFromChoice (self, dom_support, element, ctd_instance, candidate_particles):
        # Correct behavior requires that particles with a minOccurs() of 1
        # precede any particle with minOccurs() of zero; otherwise we can
        # incorrectly succeed at matching while not consuming everything
        # that's available.  This sorting was done in _setContent.
        for particle in candidate_particles:
            try:
                particle.extendDOMFromContent(dom_support, element, ctd_instance)
                return particle
            except pyxb.DOMGenerationError, e:
                pass
            except Exception, e:
                #print 'GEN CHOICE failed: %s' % (e,)
                raise
        return None

    def extendDOMFromContent (self, dom_support, element, ctd_instance):
        assert isinstance(ctd_instance, basis.complexTypeDefinition)
        if self.C_SEQUENCE == self.compositor():
            for particle in self.particles():
                particle.extendDOMFromContent(dom_support, element, ctd_instance)
        elif self.C_ALL == self.compositor():
            mutable_particles = self.particles()[:]
            while 0 < len(mutable_particles):
                try:
                    choice = self.__extendDOMFromChoice(dom_support, element, ctd_instance, mutable_particles)
                    mutable_particles.remove(choice)
                except pyxb.DOMGenerationError, e:
                    #print 'ALL failed: %s' % (e,)
                    break
            for particle in mutable_particles:
                if 0 < particle.minOccurs():
                    raise pyxb.DOMGenerationError('ALL: Could not generate instance of required %s' % (particle.term(),))
        elif self.C_CHOICE == self.compositor():
            choice = self.__extendDOMFromChoice(dom_support, element, ctd_instance, self.particles())
            if choice is None:
                raise pyxb.DOMGenerationError('CHOICE: No candidates found')
        else:
            assert False

class Wildcard (pyxb.cscRoot):
    """Placeholder for wildcard objects."""

    NC_any = '##any'            #<<< The namespace constraint "##any"
    NC_not = '##other'          #<<< A flag indicating constraint "##other"
    NC_targetNamespace = '##targetNamespace'
    NC_local = '##local'

    __namespaceConstraint = None
    def namespaceConstraint (self):
        """A constraint on the namespace for the wildcard.

        Valid values are:

         - L{Wildcard.NC_any}
         - A tuple ( L{Wildcard.NC_not}, a L{namespace<pyxb.Namespace.Namespace>} instance )
         - set(of L{namespace<pyxb.Namespace.Namespace>} instances)

        Namespaces are represented by their URIs.  Absence is
        represented by None, both in the "not" pair and in the set.
        """
        return self.__namespaceConstraint

    PC_skip = 'skip'            #<<< No constraint is applied
    PC_lax = 'lax'              #<<< Validate against available uniquely determined declaration
    PC_strict = 'strict'        #<<< Validate against declaration or xsi:type which must be available

    # One of PC_*
    __processContents = None
    def processContents (self): return self.__processContents

    def __init__ (self, *args, **kw):
        # Namespace constraint and process contents are required parameters.
        self.__namespaceConstraint = kw['namespace_constraint']
        self.__processContents = kw['process_contents']

    def matchesNode (self, ctd_instance, node):
        """Return True iff the node is a valid match against this wildcard.

        Not implemented yet: all wildcards are assumed to match all
        nodes.

        """
        # @todo check node against namespace constraint and process contents
        #print 'WARNING: Accepting node as wildcard match without validating.'
        return True

## Local Variables:
## fill-column:78
## End:
    
