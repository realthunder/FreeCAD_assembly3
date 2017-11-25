# Assembly3 Workbench for FreeCAD

Assembly3 workbench is yet another attempt to bring assembly capability to [FreeCAD](http://www.freecadweb.org/). There is the original unfinished Assembly workbench in FreeCAD source tree, and [Assembly2](https://github.com/hamish2014/FreeCAD_assembly2), which is an inspiration of this workbench, and with some code borrowed as well. The emphasis of Assembly3 is on full support of nested and multi-document assemblies. 

## Installation

At the moment of this writing, Assembly3 only works with a forked FreeCAD [branch](https://github.com/realthunder/FreeCAD/tree/LinkStage3). You need to first checkout this branch and build it yourself.

After that, checkout this repository directly inside the `Mod` directory of your FreeCAD installation. Be sure to name the directory as **asm3**. The Assembly3 workbench supports multiple constraint solver backends. Currently, there are two backends available, `SolveSpace` and `SymPy + SciPy`, both of which have external dependency. The current focus is to get SolveSpace backend fully working first, with SymPy + SciPy serving as a reference implementation for future exploration. All backends are optional. But, you'll need at least one installed to be able to do constraint based assembling, unless you are fine with manually movement, which is actually doable because Assembly3 provides a powerful mouse dragger.

### SolveSpace

[SolveSpace](http://solvespace.com/) is by itself a standalone CAD software with excellent assembly support. IMO, it has the opposite design principle of FreeCAD, which is big, modular, and fully extensible. SolveSpace, on the other hand  is lean and compact, and does extremely well for what it offers. But, you most likely will find something you want that's missing, and have to seek out other software for help. The constraint solver of SolveSpace is available as a small library for integration by third party software, which gives us the opportunity to bring the best from both worlds. 

There is no official python binding of SolveSpace at the moment. Besides, some small modification is required to bring out the SolveSpace assembly functionality into the solver library. You can find my fork at `asm3/slvs` subdirectory. To checkout, 

```
cd asm3
git submodule update --init slvs
```

If you are using Ubuntu 16.04, then you can check out the pre-built python binding at `asm3/py_slvs` subdirectory.

```
cd asm3
git submodule update --init py_slvs
```

Or, simply build your own, which is quite simple on Ubuntu. 

```
apt-get install libpng12-dev libjson-c-dev libfreetype6-dev \
                libfontconfig1-dev libgtkmm-2.4-dev libpangomm-1.4-dev \
                libgl-dev libglu-dev libglew-dev libspnav-dev cmake
```

Make sure to checkout one of the necessary sub module before building.

```
cd asm3/slvs
git submodule update --init extlib/libdxfrw 
```

To build the python binding only

```
cd asm3/slvs
mkdir build
cd build
cmake -DBUILD_PYTHON=1 ..
make _slvs
```

After compilation is done, copy `slvs.py` and `_slvs.so` from `asm3/slvs/build/src/swig/python/CMakeFiles` to `asm3/py_slvs`. Overwrite existing files if you've checked out the `py_slvs` sub module. If not, then be sure to create an empty file named `__init__.py` at `asm3/py_slvs`.

No test build has been done on other platforms. Feel free to try and submit a pull request if there is any problem. Please consult SolveSpace [build instruction](https://github.com/realthunder/solvespace#building-on-linux) for more information. 

### SymPy + SciPy

The other constraint solver backend uses [SymPy](http://www.sympy.org/) and [SciPy](https://www.scipy.org/). They are mostly Python based, with some native acceleration in certain critical parts. The backend implementation models after SolveSpace's solver design, that is, symbolic algebraic + non-linear least square minimization. It can be considered as a python implementation of the SolveSpace's solver. 

SciPy offers a dozen of different minimization algorithms, but most of which cannot compete with SolveSpace performance wise. The reasons for writing this backend are,

* SolveSpace is under GPL, which is incompatible with FreeCAD's LGPL, 
* To gain more insight of the solver system, and easy experimentation with new ideas due to its python based nature,
* For future extension, physics based simulation, maybe?

You'll need to install SymPy and SciPy for your platform. For Ubuntu, simply run

```
apt-get install python-sympy python-scipy
```

## Design

The design of Assembly3 (and the fork of FreeCAD) partially follows the unfinished FreeCAD Assembly [project plan](https://www.freecadweb.org/wiki/Assembly_project), in particularly, the section [Infrustracture](https://www.freecadweb.org/wiki/Assembly_project#Infrastructure) and [Object model](https://www.freecadweb.org/wiki/Assembly_project#Object_model), which are summarized below,

### Multi model

The forked FreeCAD core supports external object linking (with a new type of property, `PropertyXLink`, as a drop-in replacement of PropertyLink), displaying, editing, importing and exporting. An important feature that's still missing is cross document undo/redo. Currently, a single action involving external objects may generate multiple transactions across multiple documents, which is inconvenient and confusing if the user tries to undo/redo.

### Part-tree

Assembly3 provides the `Assembly` container for holding its child features (or sub-assembly), and their constraints. It also introduce a new concept of `Elements` for declaring geometry elements used by constraints inside parent assembly. The purpose of the `Element` is to minimize the problem caused by geometry topological name changing, and make the assembly easier to maintain. See the following section for more details. A single object (e.g. Part object, sketch, or another assembly), can be added to multiple parent assemblies, either within the same or located outside of the current document. Each of its appearance inside the parent assembly has independent visibility control, but shares the same placement, meaning that if you move one instance of the object, all other instances moves relative to their parent assembly container. You can have independent placement by converting a child object into a link type object (See the following section for details). Simply right click the child object in the tree view and select `Link actions -> Replace with link`.

### Unified Drag/Drop/Copy/Paste interface

The drag and drop API has been extended to let the target object know where the dropped object located in the object hierarchy, which is taken full advantage by Assembly3. The copy and paste is extended as well to be aware of external objects, and let the user decide whether to do a shallow or deep copy.

### Object model

The `SubName` field in `Gui::SelectionObject` is for holding the selected geometry sub-element, such as face, edge or vertex. The forked FreeCAD extended usage of `SubName` to hold the path of selected object within the object hierarchy, e.g. a selection object with `Object = Assembly1` and `SubName = Parts.Assembly2.Constraints002.Constraint.` means the user selected the `Constraint` object of `Assembly2`, which is a child feature of the part group (`Parts`) in `Assembly1`. Notice the ending `.` in `SubName`. This is for backward compatibility purpose, so that the `SubName` can still be used to refer to a geometry sub-element of some sub-object without any ambiguity. The rule is that, any sub-object references must end with a `.`, and those names without an ending `.` are sub-element references. The aforementioned `PropertyXLink` has an optional `subname` field (assign/return as a `tuple(obj, subname)` in Python) for linking into a sub-object/element.

`Gui.Selection` is extended with backward compatibility to provide full object path information on each selection, which makes it possible for the same object to be included in more than one group like objects without ambiguity on selection. Several new APIs have been added to FreeCAD core to provide nested child object placement and geometry information. 

## Concepts

### Coordinate System

Before starting to use the Assembly3 workbench, it is necessary for the user to be familiar with a few new concepts in FreeCAD. The user is encourage to first read [this tutorial](https://www.freecadweb.org/wiki/Assembly_Basic_Tutorial) to get some idea about the new concept of _local coordinate systems_. The tutorial is for the original unfinished Assembly workbench, but gives a pretty comprehensive overview of what Assembly3 is providing as well. The `Part` or `Product` container mentioned in the tutorial are equivalent to the `Assembly` container in Assembly3, which of course can be treated just as a _part_ and added to other assemblies. There is one thing I disagree with this tutorial. The concept of _global coordinate system_ is still useful, and necessary to interoperate with objects from other legacy (i.e. non-local-CS-aware) workbench. Let's just define the _global coordinate system_ as the 3D view coordinate system, in other word, the location where you actually see the object in the 3D view, or, the coordinates displayed in the status bar when you move your mouse over some object.

There is an existing container, `App::Part`, in upstream FreeCAD, which is a group type object that provides local coordinate system. The difference, comparing to Assembly3 container, is that one object is allowed to be added to one and only one `App::Part` container. The owner container can be added to other `App::Part` container, but must still obey the one direct parent container rule. The reason behind this is that when any object is added to `App::Part`, it is physically removed from its original parent coordinate system, and added to the owner `App::Part's` coordinate system, so the object cannot appear in more than one coordinate system. By _physically removed_, I mean the 3D visual representation data is physically moved to a different coordinate system inside the 3D scene graph (See [here](https://www.freecadweb.org/wiki/Scenegraph) for more details). 

Assembly3 container has no such restriction. When added to a Assembly3 container, the object's visual data is simply reused the inserted multiple times into the scene graph, meaning that the object actually exists simultaneously in multiple coordinate systems. This has a somewhat unexpected side effect. When an object is added to an assembly with some placement, the object is seemingly jumping into a new place. This is excepted, because the object enters a new coordinate system, and it seems to have the same behavior as `App::Part`. But what actually happened is that the original object inside the global coordinate system is simply made invisible before adding to the assembly container. You can verify this by manually toggle the `Visibility` property to reveal the object in its original placement. Every object's `Visibility` property controls its own visibility in the global coordinate system only. Each assembly container has the `VisibilityList` property to control the visibilities of its children.

### Link

The forked FreeCAD core introduced a new type of object, called _Link_. A _Link_ type object (not to be confused with a _link property_) often does not have geometry data of its own, but instead, link to other objects (using link property) for geometry data sharing. Its companion view provider, `Gui::ViewProviderLink`, links to the linked object's view provider for visual data sharing. It is the most efficient way of duplicating the same object in different places, with optional scale/mirror and material override. The core provides an extension, `App::LinkBaseExtension`, as a flexible way to help users extend their own object into a link type object. The extension utilize a so called _property design pattern_, meaning that the extension itself does not define any property, but has a bunch of pre-defined property place holders. The extension activates part of its function depending on what properties are defined in the object. This design pattern allows the object to choose their own property names and types. 

The core provides two ready-to-use link type objects, `App::Link` and `App::LinkGroup`, which expose different parts of `LinkBaseExtension's` functionality. `App::Link` supports linking to an object, either in the same or external document, and has built-in support of array (through property `ElementCount`) for efficient duplicating of the same object. `LinkGroup` acts like a group type object with local coordinate system. It relies on `LinkBaseExtension` and `ViewProviderLink` to provide advanced features like, adding external child object, adding the same object multiple times, etc. All of the Assembly3 containers are in fact customized `LinkGroup`. 

### Element

`Element` is a brand new concept introduced by Assembly3. It is used to minimize the dreadful consequences of geometry topological name changing, and also brings the object-oriented concept in the programming world into CAD assembling. `Element` can be considered as a declaration of connection interface of the owner assembly, so that other parent assembly can know which part of this assembly can be joined with others. 

For a geometry constraint based system, each constraint defines some relationship among geometry elements of some features. Conventionally, the constraint refers to those geometry elements by their topological names, such as `Fusion001.Face1`, `Cut002.Edge2`, etc. The problem with this simply approach is that the topological name is volatile. Faces or edges may be added/removed after the geometry model is modified. More sophisticated algorithm can be applied to reduce the topological name changing, but there will never be guarantee of fixed topological names. Imagine a simple but yet extreme case where the user simply wants to replace an entire child feature, say, changing the type of some screw. The two features are totally different geometry objects with different topological naming. The user has to manually find and amend geometry element references to the original child feature in multiple constraints, which may exists in multiple assembly hierarchies, across multiple documents.

The solution, presented by Assembly3, is to use abstraction by adding multiple levels of indirections to geometry references. Each `Assembly` container has an element group that contains a list of `Elements`, which are a link type of object that links to some geometry element of some child feature of this assembly. In case the feature is also an `Assembly`, then the `Element` in upper hierarchy will instead point to the `Element` inside lower hierarchy assembly. In this way, each `Element` acts as an abstraction to which geometry element can be used by other parent assemblies. Any constraint involving some assembly will only indirectly link to the geometry element through an `Element` of some child assembly. If the geometry element's topological name changes due to whatever reason, the user only need to change the deepest nested (i.e. nearest to the actual geometry object) `Element`'s link reference, and all upper hierarchy `Elements` and related constraints stays the same. 

The `Element` is a specialized `App::Link` that links into a sub-object, using a `PropertyXLink` that accepts a `tuple(object, subname)` reference. In addition, `Element` allows to be linked by its label, instead of the immutable internal FreeCAD object name. `Element` specifically allows its label to be duplicated (but still enforces uniqueness among its siblings). This enables the user to define inter-changeable parts with the same set of elements as interface. 

Let's take a look at the following assembly hierarchy for an example,

```
Assembly001
    |--Constraints001
    |       |--Constraint001
    |               |--ElementLink -> (Elements001, "$Element.")
    |               |--ElementLink001 -> (Parts001, "Assembly002.Elements002.$Element001.")
    |--Elements001
    |     |--Element -> (Parts001, "Cut.Face3")
    |--Parts001
          |--Cut
          |--Assembly002
                 |--Constraints002
                 |--Elements002
                 |      |--Element001 -> (Parts002, "Assembly003.Elements003.$Element002.")
                 |--Parts002
                       |--Assembly003
                                |--Constraints003
                                |--Elements003
                                |       |--Element002 -> (Parts003, "Fusion.Face1")
                                |--Parts003
                                       |--Fusion
```

The `Assembly001` has two child features, a `Cut` object and a child `Assembly002`, which in turn has its own child `Assembly003`. `Assembly001` contains a constraint `Constraint001` that defines the relationship of its two child features. `Constraint001` refers to two geometry element through two links, `ElementLink`, which point to a second level link, `Element`. `ElementLink001` points to `Element001`, And, because the first child feature `Cut` is not defined as an assembly, so its geometry element reference is directly stored inside the parent assembly element group. `Element001`, however, links to the lower hierarchy `Element002` in its child assembly, which again links to `Element003` in its child `Assembly003`. Notice the `$` inside the subname references. It marks the followed text to be a label instead of an object name reference. If you re-label the object, all `PropertyXLink` of all opened documents containing that label reference will be automatically updated. 

The grand idea is that, after the author modified an assembly, whether its a modification to the geometry model, or replacing some child feature. He needs to check all element references inside that and only that assembly, and make proper adjustment to correct any undesired changes. Other assemblies with elements or constraints referring to this assembly will stay the same (although recomputation is still required), even if those assemblies reside in different documents, or come from different authors.

Let's say, we have modified `Fusion`, and the original `Fusion.Face1` is now changed to `Face10`. All we need to do is to simply modify `Element002` inside the same owner assembly of `Fusion`. Everything else stays the same. 

Again, say, we want to replace `Assembly003` with some other assembly. Now this is a bit involving, because, we added `Aseembly003` directly to `Assembly002`, instead of using a link, which can be changed dynamically. The FreeCAD core has a general command to simplify this task. Right click `Assembly003` in the tree view, and select `Link actions -> Replace with link`. `Assembly003` inside `Parts002` will now be replaced with a link that links to `Assembly003`. Every relative link that involving `Parts002.Assembly003` will be updated to `Parts002.Link_Assembly003` automatically. In our case, that will be `Element001`. You can then simply change the link to point to another assembly containing an element object with the same label `Element001` (remember element object allows duplicated labels). If you still insist on adding the new assembly directly and get rid of the link, you can use `Link actions -> unlink`, and delete the link object afterward.

It may seem intimidating to maintain all these complex hierarchies of `Elements`, but the truth is that it is not mandatory for the user to manually create any element, at all. Simply select any two geometry elements in the 3D view, and you can create a constraint, regardless how many levels of hierarchies in-between. All intermediate `Elements` and `ElementLinks` will be created automatically. Although, for the sake of re-usability, it is best for the user as an assembly author to explicitly create `Element` as interfaces, and give them proper names for easy (re)assembling.

Last but not the least, `Element`, as well as the `ElementLink` inside a constraint, make use of a new core feature, `OnTopWhenSelected`, to forcefully show highlight of its referring geometry sub-element (Face, Edge, Vertex) when selected, regardless of any obscuring objects. The property `OnTopWhenSelected` is available to all view object, but default to `False`, while `Element` and `ElementLink` make it active by default. The on-top feature makes it even easier for the user to check any anomaly due to topological name changing.

### Selection

There are two types of selection in FreeCAD, geometry element selection by clicking in the 3D view, and whole object selection by clicking in the tree view. When using Assembly3, it is important to distinguish between these two types of selection, because there are now lots of objects with just one geometry element. While you are getting used to these, it is helpful to bring out the selection view (FreeCAD menu bar, `View -> Panels -> Selection view`). You select a geometry element by clicking any unselected element (Face, Edge or Vertex) in the 3D view. If you click an already selected element, the selection will go one hierarchy up. For example, for a `LinkGroup` shown below,

```
LinkGroup
    |--LinkGroup001
    |       |--Fusion
    |       |--Cut
    |--Cut001 
```

Suppose you have already selected `Fusion.Face1`. If you click that face again, the selection will go one hierarchy up, and select the whole `Fusion` object. If you click any where inside `Fusion` object again, the selection goes to `LinkGroup001`, and you'll see both `Fusion` and `Cut` being highlighted. If you again click anywhere inside `LinkGroup001`, `Cut001` will be highlighted, too, because the entire `LinkGroup` is selected. Click again in `LinkGroup`, the selection goes back to the geometry element you just clicked. 

There is a new feature in the forked FreeCAD selection view. Check the `Enable pick list` option in selection view. You can now pick any overlapping geometry elements that intersect with your mouse click in the selection view. 

You may find it helpful to turn on tree view selection synchronization (right click in tree view, select `Sync selection`), so that the tree view will automatically scroll to the object you just selected in the 3D view. When you select an originally unselected object in the tree view, the whole object will be selected. And if you start dragging the object item in the tree view, you are dragging the whole object. If you select a geometry element in the 3D view, its owner object will also be selected in tree view. But if you then initiate dragging of that particular object item, you are in fact dragging the selected geometry element. This is an important distinction, because some containers, such as the `Constraint` object, only accept dropping of geometry element, and refuse whole object dropping.

## Constraints and Solvers

As mentioned in previous section, Assembly3 supports multiple constraint solver backend. The user can choose different solver for each `Assembly`. The type of constraints available may be different for each solver. At the time of this writing, two backend are supported, one based on the solver from SolveSpace, while the other uses SymPy and SciPy, but is modeled after SolveSpace. In other word, the current two available solvers supports practically the same set of constraints and should have very similar behavior, except some difference in performance. 

Assembly3 exposed most of SolveSpace's constraints. If you want to know more about the internals, please read [this document](https://github.com/realthunder/solvespace/blob/python/exposed/DOC.txt) from SolveSpace first. The way Assembly3 uses the solver is that, for a given `Assembly`,

* Create free parameters corresponding to the placement of each movable child feature, that is, three parameters for position, and four parameters for its orientation (quaternion).
* For each constraint, create SolveSpace `Entities` (i.e. points, normals, rotations, etc) for each geometry element as a transformation of its owner feature's placement parameters.
* Create SolveSpace `Constraints` with the `Entities` created in the previous step.
* Ask SolveSpace to solve the constraints. SolveSpace formulate the constraint problems as a non-linear least square minimization problem, generates equations symbolically, and then tries to numerically find a solution for the free parameters.
* The child features placements is then updated with the found solution.

For nested assemblies, Assembly3 will always solve all the child assemblies first before the parent.

One thing to take note is that, SolveSpace is a numerical solver, which means it is sensitive to initial conditions. In other word, you must first roughly align two features according to their constraints, or else the solver may not be able to find an answer. Assembly3 has extensive support of easy manual placement of child feature. See the following section for more details.

Assembly3 provides several new constraints that are more useful for assembly purposes. Most of these constraints are in fact composite of the original constraints from SolveSpace, except for the `Lock` constraint. Some more common constraints are available as toolbar buttons for easy access, while all constraint types are accessible in property editor. Each `Constraint` object has a `Type` property, which allows the user to change the type of an existing constraint. Not all constraints require the same types of geometry elements, which means that changing the type may invalidate a constraint. The tree view will mark those invalid constraints with a red exclamation mark. Hover the mouse over those invalid items to see the explanation. Just follow the instruction to manually correct the element links.

Special mention about the `Lock` constraint, which is used to lock the placement of a related child feature. Like all other constraints, `Lock` constraint, as a container, only accepts geometry element drag and drop. If you drop in a `Vertex` or linear `Edge`, then the owner feature is allowed to be rotated around the geometry element. If you drop in a non-linear `Edge` or `Face`, then the feature is completely fixed within the owner assembly with this constraint. If no `Lock` constraint is found in an `Assembly`, then the feature that owns the first element of the first constraint is fixed.

## Comparing with Assembly2

This section is for those who have used [Assembly2](https://github.com/hamish2014/FreeCAD_assembly2) before. Here is a brief list of comparison between Assembly2 to Assembly3. 

* Assembly2 supports only one assembly per document, so the document can be considered as the assembly container.

  Assembly3 has dedicated container for assembly and supports multiple nested assemblies per document. 

* Assembly2 has dedicated object for imported child feature. The child feature's geometry is imported as a compound, and can be updated by user in case of external modification of the geometry model. 

  Assembly3 has no special object for imported feature, although the feature may be added through a link under some circumstances. Simply drag and drop feature into an `Assembly` container, even if the feature is in another document. Any modification of the feature is instantaneously visible to its parent assembly. The FreeCAD core provides various commands to help navigating among nested assemblies and the linked child features, import the external feature into the same document of the assembly, and export the child feature into external document.

* In Assembly2, the imported child feature acts as a container to group related constraints. There is no visualization of the geometry element in the constraint. 

  The Assembly3 constraints are grouped under the parent assembly, each constraint acts as a container of its referring geometry `ElementLink`, with enhanced visualization support. Simply right click the `ElementLink` and choose `Link actions -> Select final linked object` to jump to the actual geometry model object owning the geometry element.

* Assembly2 has a dedicate task panel for degree of freedom animation.

  Assembly3 is currently lacking of similar functionality. However, it does allow you to interactively drag any part of the assembly under constraint in real time.

## Common Operations

We are going to build a simply assembly through this section to showcase some of the main features of Assembly3

### Create a Simply Assembly with a Constraint

* Start FreeCAD, and create a new document
* Switch to `Part` workbench, and create a `Cube` and a `Cylinder`
* Switch to `Assembly3` workbench, click ![Add assembly](/Gui/Resources/icons/Assembly_New_Assembly.svg) to create a new assembly
* Select both the `Cube` and `Cylinder`, and drag them into the new assembly
* Select any face of the `Cylinder` or `Cube`, and click ![Move](/Gui/Resources/icons/Assembly_Move.svg) to activate part manual movement. Click any arrow to drag the `Cylinder` on top of the `Cube`
* Select the top face of `Cut` and (while holding `CTRL` key) select the bottom face or edge of the `Cylinder`, and then click ![Add Coincidence](/Gui/Resources/icons/constraints/Assembly_ConstraintCoincidence.svg) to create a plane coincidence constraint.
* Finally, click ![Solve](/Gui/Resources/icons/AssemblyWorkbench.svg) to solve the constraint system.

![Screencast1](https://github.com/realthunder/files/blob/master/screencast/asm3/asm1.gif)

You can click ![Auto recompute](/Gui/Resources/icons/Assembly_AutoRecompute.svg) to enable auto-solving with any changes in constraint.

Now, save this document with whatever name you like.

### Create a Super Assembly with External Link Array

We are going to build a multi-joint _thing_ using the above assembly as the base part.

* Create a new document, and save it to whatever name you like. Yes, you need to save both the link and linked document at least once for external linking to work, because `PropertyXLink` need the file path information of both document to calculate relative path.
* Make sure the current active 3D view is the new empty document. Now, in the tree view, select the assembly we just created previously, and then hold on `CTRL` key and right click the new document item in the tree view, and select `Link actions -> Make link`. A `Link` will be created that brings the assembly into the new document. You probably need to click `Fit content` button (or press `V,F` in 3D view) to see the assembly.
* Select the link in the tree view, and change the `ElementCount` property to four. Now you have four identical assemblies.
* Create a new assembly, and then drag the link object into it.
* Select any face of any `Cube`, click ![Move](/Gui/Resources/icons/Assembly_Move.svg) and drag to spread out the parts.
* Select any face of the left most `Cube` in 3D view, and click ![Lock](/Gui/Resources/icons/constraints/Assembly_ConstraintLock.svg) to lock the left most sub assembly. 
* Orient the parts whatever you like. Select two face from any two assembly, and create a plane coincidence constraint. If you've enabled _auto recompute_, then the two assembly will now to snapped together
* Do the same for the rest of the parts.

![Screencast2](https://github.com/realthunder/files/blob/master/screencast/asm3/asm2.gif)

Now that we've made this multi-joint thingy, try to save this document, and FreeCAD will ask if you want to save the external document, too. If you answer yes, then FreeCAD will take care of ordering, and save the external document first before linking document.

Close both documents. Open the multi-joint assembly document, FreeCAD will automatically open any externally referenced documents, too. If you close the external document while leaving the linking document open, all externally linked object will vanish from 3D view. Open external document again and the objects will re-appear. This allows you to easily swap in a replacement document for whatever reason. But, it demands the replacement document having an object of the same internal name as the original linked one. You can of course, easily re-assign the link to any other object in the opened documents. Just use the property editor, click the edit button of `LinkedObject` property. In the editor window, select the desired document in the drop list, and then select the desired object. But now, you need to make sure the new linked object has the same element interface, or else the constraints will be broken.

A few more words about link array. Assembly3 normally treats any object added to its part group as a stand alone entity that can be moved as a whole. However, it has special treatment for a link array object. Each array element will be treated as separate entities, that can be constrained and moved individually. If you actually want to add the array as an integral part, simply wrap the array inside a dummy assembly without any constraint, and add that assembly instead into the parent assembly. 

By the way, the `Draft` workbench now has two variation of link array, the `LinkArray` and `LinkPathArray`, which provide the same functionality as `Draft` `Array` and `PathArray`, but use link to provide duplicates. Those link arrays, by default, do not show individual element in tree view. You can still access the each element through `subname` reference as usual. Having less objects can improve document saving and loading performance. It is particularly noticeable if you have large amount of array elements. You can, however, show the array element at any time by toggle property `ShowElement`. Once the elements are visible, they can be moved independently by change their placements.

### Add/Modify Element and ElementLink

It is quite easy to directly create a new constraint as shown above, with all involved `Element` and `ElementLink` being taken care of for you by Assembly3. It is also straightforward to manually add new or modify existing `Elements` and `ElementLink`. Simply select a geometry element in 3D view, and its corresponding owner object will be selected in the tree view (Remember to turn on `Sync selection` option in tree view as mentioned before). You can then drag the selected item to the `ElementGroup` of an `Assembly` to create a new `Element`, or to a `Constraint` to add an `ElementLink`. You can modify an existing `Element` or `ElementLink` by simply dragging the item onto an existing item of `Element` or `ElementLink`.

### Part Move

Assembly3 has extensive support of manual movement of nested assembly. In 3D view, select any geometry element (Face, Edge) that belongs to some assembly, and click ![Move](/Gui/Resources/icons/Assembly_Move.svg) to activate part dragging. The dragger will be centered around the selected geometry element. In case of multi-hierarchy assemblies, you will be dragging the first level sub-assembly of the top-level assembly. If you want to drag intermediate sub-assembly instead, add that assembly as the second selection (`CTRL` select) before activating part move. 

If you have enabled ![Auto recompute](/Gui/Resources/icons/Assembly_AutoRecompute.svg), any movement of the sub-assembly will cause the parent assembly to auto re-solve its constraints, as shown below. Because there are too many degree of freedom left, hence many possible solutions of the constraint system, the movement of the multi-joint assembly is jerky. Besides, the part move command is very complicated, and probably need a lot more work to make it perfect. In case when the parts are moved such that they stuck in some invalid position, as you can see from the screen cast below, simply `CTRL+Z` to undo the movement. Every time you release the mouse button, a transaction will be committed, so that you can undo/redo the previous mouse drag. You can also temporary bypass recomputation by holding `CTRL` key while dragging.


![Screencast3](https://github.com/realthunder/files/blob/master/screencast/asm3/asm3.gif)


### Import External Assembly

In some cases, it will be easier to distribute your multi-hierarchy assembly as a single self-contained document. FreeCAD core provides a convenient command to help with this otherwise not so trivial task. Simply right-click any item in the document you want to distribute, and select `Link actions -> Import all links`, and that's all. Click ![Solve](/Gui/Resources/icons/AssemblyWorkbench.svg) to see if every thing is okay. You can of course selectively import any object you want. Simply right click that item and select `Link actions -> Import link`.

