import maya.cmds as cmds
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
from functools import partial
import json as json
import os as os

##########################
#### Helper Functions ####
##########################

# Convert screen space to world space
# https://forums.autodesk.com/t5/maya-programming/getting-click-position-in-world-coordinates/td-p/7578289
def screenSpaceToWorldSpace(screenPoint):
    worldPos = om.MPoint() # out variable
    worldDir = om.MVector() # out variable
    
    activeView = omui.M3dView().active3dView()
    activeView.viewToWorld(int(screenPoint[0]), int(screenPoint[1]), worldPos, worldDir)
    
    return worldPos

# Convert world space to screen space
# https://video.stackexchange.com/questions/23382/maya-python-worldspace-to-screenspace-coordinates
def worldSpaceToScreenSpace(worldPoint):
    # Find the camera
    view = omui.M3dView.active3dView()
    cam = om.MDagPath()
    view.getCamera(cam)
    camPath = cam.fullPathName()
    
    # Get the dagPath to the camera shape node to get the world inverse matrix
    selList = om.MSelectionList()
    selList.add(cam)
    dagPath = om.MDagPath()
    selList.getDagPath(0,dagPath)
    dagPath.extendToShape()
    camInvMtx = dagPath.inclusiveMatrix().inverse()

    # Use a camera function set to get projection matrix, convert the MFloatMatrix 
    # into a MMatrix for multiplication compatibility
    fnCam = om.MFnCamera(dagPath)
    mFloatMtx = fnCam.projectionMatrix()
    projMtx = om.MMatrix(mFloatMtx.matrix)

    # Multiply all together and do the normalisation
    mPoint = om.MPoint(worldPoint[0],worldPoint[1],worldPoint[2]) * camInvMtx * projMtx
    x = (mPoint[0] / mPoint[3] / 2 + .5)
    y = 1 - (mPoint[1] / mPoint[3] / 2 + .5)
    
    return [x,y]

# Collect all objects in the scene using Maya ls command
# https://stackoverflow.com/questions/22794533/maya-python-array-collecting
def collectObjects(currSel):
    meshSel = []
    for xform in currSel:
        shapes = cmds.listRelatives(xform, shapes=True) # it's possible to have more than one
        if shapes is not None:
            for s in shapes:
                if cmds.nodeType(s) == 'mesh':
                    meshSel.append(xform)
  
    return meshSel

# Test if the mesh is bounded by the coordinates
# https://boomrigs.com/blog/2016/1/12/how-to-get-mesh-vertex-position-through-maya-api
def testMesh(mesh, bounds):    
    # Store bounds
    left = bounds[0][0]
    right = bounds[0][1]
    top = bounds[1][0]
    bottom = bounds[1][1]
    
    # Get Api MDagPath for object
    activeList = om.MSelectionList()
    activeList.add(mesh)
    dagPath = om.MDagPath()
    activeList.getDagPath(0, dagPath)

    # Iterate over all the mesh vertices and get position
    mItEdge = om.MItMeshEdge(dagPath)
    while not mItEdge.isDone():    	
        startPoint = mItEdge.point(0, om.MSpace.kWorld)
        endPoint = mItEdge.point(1, om.MSpace.kWorld)
        
        # Return with a True value if the edge is within the boundaries
        if clippingTest(startPoint, endPoint, bounds):
            return True
                
        mItEdge.next()
    
    return False
    
# Perform the Cohen-Sutherland Clipping test using Op Codes
# https://en.wikipedia.org/wiki/Cohen%E2%80%93Sutherland_algorithm
def clippingTest(p, q, bounds):
    P = worldSpaceToScreenSpace(p)
    Q = worldSpaceToScreenSpace(q)
    opCodeP = opCode(P, bounds)
    opCodeQ = opCode(Q, bounds)
        
    # Trivial reject
    if (opCodeP & opCodeQ):
        return False
        
    return True

# Return the Op Code for a given point
def opCode(p, bounds):
    code = 0
    
    # Left of clipping window
    if p[0] < bounds[0][0]:
        code = code | 1
    
    # Right of clipping window
    if p[0] > bounds[0][1]:
        code = code | 2
        
    # Above clipping window
    if p[1] < bounds[1][0]:
        code = code | 4
        
    # Below clipping window
    if p[1] > bounds[1][1]:
        code = code | 8
        
    return code

# Return correct shader given a shader name
def findShader(mesh):
    cmds.select(mesh)
    nodes = cmds.ls(sl=True, dag=True, s=True)
    shadingEngine = cmds.listConnections(nodes, type='shadingEngine')
    materials = cmds.ls(cmds.listConnections(shadingEngine), materials=True)
    
    # Find the OSL shader node from connected nodes of the material
    for node in cmds.listConnections(materials):
        if node.find('PxrOSL') > -1:
            return node
    return None

# Extract semantic data based on block position and meshes in block
def extractSemantics(meshes, screenPoint, neighbors, border):
    semantics = []
    
    for mesh in meshes:
        semanticsForMesh = []
        semanticsForNeighbors = []
        
        # Calculate semantics for mesh
        translation = formatList( cmds.xform(mesh, q=1, ws=1, t=1) )
        rotation = formatList( cmds.xform(mesh, q=1, ws=1, rp=1) )
        scaling = formatList( cmds.xform(mesh, q=1, ws=1, s=1) )
        worldPoint = screenSpaceToWorldSpace(screenPoint)
        d = postionDistance(meshPosition(mesh), worldPoint)
        
        # Basic JSON formatting
        # semanticsForMesh.append('d : {:.3f}'.format( d ))
        # semanticsForMesh.append('t : [{:.3f}, {:.3f}, {:.3f}]'.format( translation[0], translation[1], translation[2] ))
        # semanticsForMesh.append('r : [{:.3f}, {:.3f}, {:.3f}]'.format( rotation[0], rotation[1], rotation[2] ))
        # semanticsForMesh.append('s : [{:.3f}, {:.3f}, {:.3f}]'.format( scaling[0], scaling[1], scaling[2] ))
        # semantics.append('{} : {}'.format( mesh, semanticsForMesh ))
        
        # Plain text formatting
        semanticsForMesh.append('{} with dist {:06d}'.format( mesh, int( d * 1e6 ) ))
        semantics.append(semanticsForMesh)
                
    return semantics
    
def formatList(list):
    for i, val in enumerate(list):
        if float('{0:.6f}'.format( val )) == -0.0:
            list[i] = 0.0
            
    return list

# Return the Euclidean distance between the centers of two meshes
def findDistance(meshA, meshB):
    return postionDistance(meshPosition(meshA), meshPosition(meshB))

# Obtain the position of a mesh in world space
def meshPosition(mesh):
    cmds.select(mesh)
    return cmds.xform( q=True, ws=True, t=True )

# Find the distance between two points
def postionDistance(posA, posB):
    return ((posA[0] - posB[0])**2 + (posA[1] - posB[1])**2 + (posA[2] - posB[2])**2)**0.5

# Makes a folder if none exists for the input path
# https://stackoverflow.com/questions/47738227/create-a-folder-using-python-in-a-maya-program
def make_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

##########################
### Main Functionality ###
##########################

# Create and display menu system
def displayWindow():
    menu = cmds.window( title="Extract Semantics Tool", iconName='ExtractSemanticsTool', widthHeight=(350, 400) )
    scrollLayout = cmds.scrollLayout( verticalScrollBarThickness=16 )
    cmds.flowLayout( columnSpacing=10 )
    cmds.columnLayout( cat=('both', 25), rs=10, cw=340 )
    cmds.text( label="\nThis is the \"Extract Sematics Tool\"! This tool will extract semantics for the loaded scene.\n\n", ww=True, al="left" )
    cmds.text( label="To run:\n1) Input the information in the fields below.\n2) Click \"Run\".", al="left" )
    cmds.text( label='Enter the keyframe at which to start semantics generation (1):', al='left', ww=True )
    startTimeField = cmds.textField()
    cmds.text( label='Enter the keyframe at which to end semantics generation (1):', al='left', ww=True )
    endTimeField = cmds.textField()
    cmds.text( label='Enter the step at which to process frames (1):', al='left', ww=True )
    stepTimeField = cmds.textField()
    cmds.text( label='Enter the border distance for generating semantics (0):', al='left', ww=True )
    borderField = cmds.textField()
    cmds.text( label='Enter the dimension for each extracted image, a power of 2 is recommended (64):', al='left', ww=True )
    dimensionField = cmds.textField()
    cmds.button( label='Run', command=partial( generateSemantics, menu, startTimeField, endTimeField, stepTimeField, borderField, dimensionField ) )
    cmds.text( label="\n", al='left' )
    cmds.showWindow( menu )

def generateSemantics( menu, startTimeField, endTimeField, stepTimeField, borderField, dimensionField, *args ):
    # Grab user input and delete window
    startTime = cmds.textField(startTimeField, q=True, tx=True )
    if (startTime == ''):
        print 'WARNING: Default start time (1) used...'
        startTime = '1'
    endTime = cmds.textField(endTimeField, q=True, tx=True )
    if (endTime == ''):
        print 'WARNING: Default end time (1) used...'
        endTime = '1'
    stepTime = cmds.textField(stepTimeField, q=True, tx=True )
    if (stepTime == ''):
        print 'WARNING: Default step time (1) used...'
        stepTime = '1'
    border = cmds.textField(borderField, q=True, tx=True )
    if (border == '' or int(border) < 0):
        print 'WARNING: Default border (0) used...'
        border = '0'
    dimension = cmds.textField(dimensionField, q=True, tx=True )
    if (dimension == ''):
        print 'WARNING: Default dimension (64) used...'
        dimension = '64'
    dim = int(dimension)
    cmds.deleteUI( menu, window=True )
    cmds.currentTime( int(startTime), edit=True )
    currTime = startTime
    
    # Set up program
    resWidth = cmds.getAttr('defaultResolution.width')
    resHeight = cmds.getAttr('defaultResolution.height')
    blockDim = [dim, dim]
    print(resWidth, resHeight, blockDim)
    xDiv = float(resWidth) / blockDim[0]
    yDiv = float(resHeight) / blockDim[1]
    
    # Obtain all meshes in the scene
    currSel = cmds.ls()
    meshes = collectObjects(currSel)
    
    # Iterate over range of frames
    while int(currTime) <= int(endTime):
        print('Processing frame {:03d}'.format(int(currTime)))
    
        # Set up blocks
        blocks = []
        blockToMeshMap = []
        meshBlocks = {}
        for h in range(int(yDiv)):
            row = []
            blockToMeshMap.append([])
            
            # Find boundaries for each block in the row
            top = h / yDiv
            bottom = (h + 1) / yDiv
            for w in range(int(xDiv)):
                left = w / xDiv
                right = (w + 1) / xDiv
                
                row.append([[left,right],[top,bottom]])
                blockToMeshMap[h].append([])
                
            # Append the finished row
            blocks.append(row)
                
        #print('Block Dim: (%d, %d), Blocks: (%d, %d)' % (blockDim[0], blockDim[1], len(blocks), len(blocks[0])))
    
        # Iterate over all meshes and all boundaries
        for k, mesh in enumerate(meshes):
            cmds.select(mesh)
            bb = cmds.xform( q=True, bb=True, ws=True )
            
            # Obtain all 8 points to test from the bounding box
            # Format: xmin ymin zmin xmax ymax zmax
            bbPoints = []
            bbPoints.append(om.MPoint( bb[0], bb[1], bb[2], 1.0 ))
            bbPoints.append(om.MPoint( bb[0], bb[1], bb[5], 1.0 ))
            bbPoints.append(om.MPoint( bb[0], bb[4], bb[2], 1.0 ))
            bbPoints.append(om.MPoint( bb[0], bb[4], bb[5], 1.0 ))
            bbPoints.append(om.MPoint( bb[3], bb[1], bb[2], 1.0 ))
            bbPoints.append(om.MPoint( bb[3], bb[1], bb[5], 1.0 ))
            bbPoints.append(om.MPoint( bb[3], bb[4], bb[2], 1.0 ))
            bbPoints.append(om.MPoint( bb[3], bb[4], bb[5], 1.0 ))
            
            # Translate to screen space and obtain overall bounds
            left, right, top, bottom = 1.0, 0.0, 1.0, 0.0
            for p in bbPoints:
                P = worldSpaceToScreenSpace(p)
                if left > P[0]:
                    left = P[0]
                if right < P[0]:
                    right = P[0]
                if top > P[1]:
                    top = P[1]
                if bottom < P[1]:
                    bottom = P[1]
                        
            if left < 0.0 or left >= 1.0:
                left = 0.0
            if right > 1.0 or right <= 0.0:
                right = 1.0
            if top < 0.0 or top >= 1.0:
                top = 0.0
            if bottom > 1.0 or bottom <= 0.0:
                bottom = 1.0
            
            # Translate bounds to i and j values
            bounds = [int(left * len(blocks[0])) - int(border), int(right * len(blocks[0])) + 1 + int(border), int(top * len(blocks)) - int(border), int(bottom * len(blocks)) + 1 + int(border)]
            if bounds[0] > len(blocks[0]) - 1:
                bounds[0] = len(blocks[0]) - 1
            if bounds[1] > len(blocks[0]) - 1:
                bounds[1] = len(blocks[0]) - 1
            if bounds[2] > len(blocks) - 1:
                bounds[2] = len(blocks) - 1
            if bounds[3] > len(blocks) - 1:
                bounds[3] = len(blocks) - 1
            
            #print('Processing {}: [({},{}),({},{})]'.format(mesh, bounds[0], bounds[1], bounds[2], bounds[3]))
            for i in range(bounds[2], bounds[3] + 1):
                for j in range(bounds[0], bounds[1] + 1):
                    # Test which meshes are contained within the block
                    #subBounds = blocks[i][j]
                    #if testMesh(mesh, subBounds):
                    if blockToMeshMap[i][j] is None:
                        blockToMeshMap[i][j] = [mesh]
                    else:
                        blockToMeshMap[i][j].append(mesh)
                            
        # Extract semantics for each mesh
        framePath = 'C:\\Users\\wesha\\Git\\dynamic_frame_generator\\python\\attngan\\data\\frame\\text\\{:03d}'.format( int(currTime) )
        make_dir(framePath)
        for i, data in enumerate(blockToMeshMap):
            for j, meshesInBlock in enumerate(data):
                if meshesInBlock:
                    # Screen point = Ydim * (i + 1), Xdim * (j + 1)
                    screenPoint = blockDim[1] * (i + 0.5), blockDim[0] * (j + 0.5)
                    semantics = extractSemantics(meshesInBlock, screenPoint, meshes, float(border))

                    #print('Processing semantics for block({},{})'.format( i, j ))
                    blockPath = framePath + '\\{:03d}.txt'.format( int(i * xDiv + j + 1) )
                    with open(blockPath, 'w') as f:
                        for row in semantics:
                            if len(row) <= 1:
                                f.write( ''.join(row) )
                            else:
                                prefix = ''
                                for k, caption in enumerate(row):
                                    if k > 0:
                                        prefix = ' and '
                                    # Write data to an output file
                                    f.write( prefix.join( caption ) )
                            f.write( '\n' )
        
        # Move to next frame
        cmds.currentTime( int(currTime) + int(stepTime), edit=True )
        currTime = int(currTime) + int(stepTime)
    
##########################
####### Run Script #######
##########################

# Display window
displayWindow()