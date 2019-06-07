# Assembly3 Workbench for FreeCAD

[![Patreon](https://img.shields.io/badge/patreon-donate-blue.svg)](https://www.patreon.com/thundereal)
[![Liberapay](http://img.shields.io/liberapay/patrons/realthunder.svg?logo=liberapay)](https://liberapay.com/realthunder/donate)
[![paypal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.me/realthunder)

Assembly3 workbench is yet another attempt to bring assembly capability to
[FreeCAD](http://www.freecadweb.org/). There is the original unfinished
Assembly workbench in FreeCAD source tree, and
[Assembly2](https://github.com/hamish2014/FreeCAD_assembly2), which is an
inspiration of this workbench, and with some code borrowed as well. The
emphasis of Assembly3 is on full support of nested and multi-document
assemblies. 

You can find more details at Assembly3 [wiki](../../wiki/Home).

__Update__: I have added a donation button. Feel free to show your support, and
thanks in advance!

## Installation

Although Assembly3 workbench is written in Python, it depends on a few external
python extensions. In addition, it relies on quite a few FreeCAD core changes
to work properly. At the moment of this writing, these changes have not been
merged into upstream yet, and only exists as a forked branch. __To save you all
the trouble of building FreeCAD yourself, I [release](../../releases) Assembly3
along with the pre-build FreeCAD for all three major platforms.__
If you want to build everything yourself, please check out the build
instruction [here](../../wiki/Build-Instruction).

## Design

The design of Assembly3 (and the fork of FreeCAD) partially follows the
unfinished FreeCAD Assembly [project plan](https://www.freecadweb.org/wiki/Assembly_project), 
in particularly, the section [Infrastructure](https://www.freecadweb.org/wiki/Assembly_project#Infrastructure)
and [Object model](https://www.freecadweb.org/wiki/Assembly_project#Object_model).
You can find more details at [here](../../wiki/Design).

## Usage

Before starting to use the Assembly3 workbench, it is necessary for the user to
be familiar with a few new [concepts](../../wiki/Concepts) introduced by the forked
FreeCAD. 

You can find instructions on common operations along with some tutorials at 
[here](../../wiki/Usage).

## Comparing with Assembly2

This section is for those who have used
[Assembly2](https://github.com/hamish2014/FreeCAD_assembly2) before. Here is
a brief list of comparison between Assembly2 to Assembly3. 

* Assembly2 supports only one assembly per document, so the document can be
  considered as the assembly container.

  Assembly3 has dedicated container for assembly and supports multiple nested
  assemblies per document. 

* Assembly2 has dedicated object for imported child feature. The child
  feature's geometry is imported as a compound, and can be updated by user in
  case of external modification of the geometry model. 

  Assembly3 has no special object for imported feature, although the feature
  may be added through a link under some circumstances. Simply drag and drop
  feature into an `Assembly` container, even if the feature is in another
  document. Any modification of the feature is instantaneously visible to its
  parent assembly. The FreeCAD core provides various commands to help
  navigating among nested assemblies and the linked child features, import the
  external feature into the same document of the assembly, and export the child
  feature into external document.

* In Assembly2, the imported child feature acts as a container to group related
  constraints. There is no visualization of the geometry element in the
  constraint. 

  The Assembly3 constraints are grouped under the parent assembly, each
  constraint acts as a container of its referring geometry `ElementLink`, with
  enhanced visualization support. Simply right click the `ElementLink` and
  choose `Link actions -> Select final linked object` to jump to the actual
  geometry model object owning the geometry element.

* Assembly2 has a dedicate task panel for degree of freedom animation.

  Assembly3 is currently lacking of similar functionality. However, it does
  allow you to interactively drag any part of the assembly under constraint in
  real time.

