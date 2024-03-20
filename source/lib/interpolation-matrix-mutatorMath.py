#coding=utf-8


'''
Interpolation Matrix
v0.7
Interpolation matrix implementing Erik van Blokland’s MutatorMath objects (https://github.com/LettError/MutatorMath)
in a grid/matrix, allowing for easy preview of inter/extrapolation behavior of letters while drawing in Robofont.
As the math is the same to Superpolator’s, the preview is as close as can be to Superpolator output,
although you don’t have as fine a coordinate system with this matrix (up to 15x15).

(The standalone script will work only on Robofont from versions 1.6 onward)
(For previous versions of Robofont (tested on 1.5 only) you can use the extension)

Loïc Sander
'''

from mutatorMath.objects.location import Location
from mutatorMath.objects.mutator import buildMutator
from fontMath.mathKerning import MathKerning

from matrixSpot import MatrixMaster, MatrixSpot, getKeyForValue, getValueForKey, splitSpotKey

from vanilla import *
from vanilla.dialogs import putFile, getFile
from defconAppKit.controls.fontList import FontList
from defconAppKit.tools.textSplitter import splitText
from defconAppKit.windows.progressWindow import ProgressWindow
from mojo.glyphPreview import GlyphPreview
from mojo.events import addObserver, removeObserver
from mojo.extensions import getExtensionDefaultColor, setExtensionDefaultColor
from AppKit import NSColor, NSThickSquareBezelStyle, NSFocusRingTypeNone, NSBoxCustom, NSBezelBorder, NSLineBorder
from math import cos, sin, pi
from time import time
import os
import re

MasterColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.1, 0.2, 1)
BlackColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 1)
GlyphBoxFillColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.4, 0.4, .1)
GlyphBoxTextColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.4, 0.4, 1)
GlyphBoxBorderColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 1, 1, 1)
Transparent = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0)

def makePreviewGlyph(glyph, fixedWidth=True):
    if glyph is not None:
        components = glyph.components
        font = glyph.getParent()
        previewGlyph = RGlyph()

        if font is not None:
            for component in components:
                base = font[component.baseGlyph]
                if len(base.components) > 0:
                    base = makePreviewGlyph(base, False)
                decomponent = RGlyph()
                decomponent.appendGlyph(base)
                decomponent.scaleBy((component.scale[0], component.scale[1]))
                decomponent.moveBy((component.offset[0], component.offset[1]))
                previewGlyph.appendGlyph(decomponent)
            for contour in glyph.contours:
                previewGlyph.appendContour(contour)

            if fixedWidth:
                previewGlyph.width = 1000
                previewGlyph.leftMargin = previewGlyph.rightMargin = (previewGlyph.leftMargin + previewGlyph.rightMargin)/2
                previewGlyph.scaleBy((.75, .75), (previewGlyph.width/2, 0))
                previewGlyph.moveBy((0, -50))

            scaleFactor = 1000.0 / font.info.unitsPerEm
            previewGlyph.scaleBy((scaleFactor, scaleFactor), (previewGlyph.width/2, 0))

            previewGlyph.name = glyph.name

        return previewGlyph
    return

def errorGlyph():
    glyph = RGlyph()
    glyph.width = 500
    pen = glyph.getPen()

    l = 50
    p = (220, 150)
    a = pi/4
    pen.moveTo(p)
    px, py = p
    for i in range(12):
        x = px+(l*cos(a))
        y = py+(l*sin(a))
        pen.lineTo((x, y))
        px = x
        py = y
        if i%3 == 0:
            a -= pi/2
        elif i%3 != 0:
            a += pi/2
    pen.closePath()

    return glyph

def fontName(font):
    familyName = font.info.familyName
    styleName = font.info.styleName
    if familyName is None:
        familyName = font.info.familyName = 'Unnamed'
    if styleName is None:
        styleName = font.info.styleName = 'Unnamed'
    return ' > '.join([familyName, styleName])

def colorToTuple(color): # convert NSColor to rgba tuple
    return color.redComponent(), color.greenComponent(), color.blueComponent(), color.alphaComponent()

def areComponentsCompatible(glyphs):
    componentCombinations = set(tuple(sorted(c.baseGlyph for c in g.components)) for g in glyphs)
    return len(componentCombinations) == 1

class InterpolationMatrixController:

    def __init__(self):
        bgColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(255, 255, 255, 255)
        buttonColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 255)
        self.w = Window((1000, 400), 'Interpolation Matrix', minSize=(470, 300))
        self.w.getNSWindow().setBackgroundColor_(bgColor)
        self.w.glyphTitle = Box((10, 10, 200, 30))
        self.w.glyphTitle.name = EditText((5, 0, -5, 20), 'No current glyph', self.changeGlyph, continuous=False)
        glyphEdit = self.w.glyphTitle.name.getNSTextField()
        glyphEdit.setBordered_(False)
        glyphEdit.setBackgroundColor_(Transparent)
        glyphEdit.setFocusRingType_(NSFocusRingTypeNone)
        self.axesGrid = {'horizontal': 3, 'vertical': 1}
        self.gridMax = 15
        self.masters = []
        self.mutatorMasters = []
        self.rawMasters = []
        self.matrixSpots = {}
        self.mutator = None
        self.currentGlyph = None
        self.errorGlyph = errorGlyph()
        self.buildMatrix((self.axesGrid['horizontal'], self.axesGrid['vertical']))
        self.w.addColumn = SquareButton((-80, 10, 30, 30), u'+', callback=self.addColumn)
        self.w.removeColumn = SquareButton((-115, 10, 30, 30), u'-', callback=self.removeColumn)
        self.w.addLine = SquareButton((-40, -40, 30, 30), u'+', callback=self.addLine)
        self.w.removeLine = SquareButton((-40, -72, 30, 30), u'-', callback=self.removeLine)
        for button in [self.w.addColumn, self.w.removeColumn, self.w.addLine, self.w.removeLine]:
            button.getNSButton().setBezelStyle_(10)
        self.w.generate = GradientButton((225, 10, 100, 30), title=u'Generate…', callback=self.generationSheet)
        self.w.loadMatrix = GradientButton((430, 10, 70, 30), title='Load', callback=self.loadMatrixFile)
        self.w.saveMatrix = GradientButton((505, 10, 70, 30), title='Save', callback=self.saveMatrix)
        self.w.clearMatrix = GradientButton((580, 10, 70, 30), title='Clear', callback=self.clearMatrix)
        addObserver(self, 'updateMatrix', 'currentGlyphChanged')
        addObserver(self, 'updateMatrix', 'fontDidClose')
        addObserver(self, 'updateMatrix', 'mouseUp')
        addObserver(self, 'updateMatrix', 'keyUp')
        self.w.bind('close', self.windowClose)
        self.w.bind('resize', self.windowResize)
        self.w.open()

    def defineWeight(self, axesGrid):
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        pass

    def buildMatrix(self, axesGrid):
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        if hasattr(self.w, 'matrix'):
            delattr(self.w, 'matrix')
        self.w.matrix = Group((0, 50, -50, -0))
        matrix = self.w.matrix
        windowPosSize = self.w.getPosSize()
        cellXSize, cellYSize = self.glyphPreviewCellSize(windowPosSize, axesGrid)

        for i in range(nCellsOnHorizontalAxis):
            ch = getKeyForValue(i)

            for j in range(nCellsOnVerticalAxis):

                spotKey = '%s%s'%(ch, j)

                if not spotKey in self.matrixSpots:
                    matrixSpot = MatrixSpot((i, j))
                    matrixSpot.setWeights(((i+1)*100, (j+1)*100))
                    self.matrixSpots[spotKey] = matrixSpot

                elif spotKey in self.matrixSpots:
                    matrixSpot = self.matrixSpots[spotKey]

                setattr(matrix, spotKey, Group(((i*cellXSize)-i, (j*cellYSize), cellXSize, cellYSize)))
                xEnd = yEnd = -2
                if i == nCellsOnHorizontalAxis-1:
                    xEnd = -3
                if j == nCellsOnVerticalAxis-1:
                    yEnd = -3
                bSize = (2, 2, xEnd, yEnd)

                cell = getattr(matrix, spotKey)
                cell.background = Box(bSize)
                cell.selectionMask = Box(bSize)
                cell.selectionMask.show(False)
                cell.masterMask = Box(bSize)
                cell.masterMask.show(False)
                for box in [cell.background, cell.selectionMask, cell.masterMask]:
                    box = box.getNSBox()
                    box.setBoxType_(NSBoxCustom)
                    box.setFillColor_(GlyphBoxFillColor)
                    box.setBorderWidth_(2)
                    box.setBorderColor_(GlyphBoxBorderColor)
                cell.glyphView = GlyphPreview(bSize)
                cell.button = SquareButton((0, 0, -0, -0), None, callback=self.pickSpot)
                cell.button.spot = matrixSpot.get()
                # cell.button.getNSButton().setBordered_(False)
                cell.button.getNSButton().setTransparent_(True)
                cell.coordinate = TextBox((5, -17, 30, 12), matrixSpot.getReadableSpot(), sizeStyle='mini')
                cell.coordinate.getNSTextField().setTextColor_(GlyphBoxTextColor)
                hWeight, vWeight = matrixSpot.getWeights()
                cell.locationHvalue = EditText((-40, (cellYSize/2)-8, 36, 16), str(hWeight), sizeStyle='mini', callback=self.setSpotRatio, continuous=False)
                if nCellsOnHorizontalAxis <= 1:
                    cell.locationHvalue.show(False)
                cell.locationVvalue = EditText(((cellXSize/2)-18, -18, 36, 16), str(vWeight), sizeStyle='mini', callback=self.setSpotRatio, continuous=False)
                if nCellsOnVerticalAxis <= 1:
                    cell.locationVvalue.show(False)
                for editInput in [cell.locationVvalue, cell.locationHvalue]:
                    e = editInput.getNSTextField()
                    e.setBordered_(False)
                    e.setBackgroundColor_(Transparent)
                    e.setFocusRingType_(NSFocusRingTypeNone)
                    editInput.spot = matrixSpot.get()
                cell.name = TextBox((7, 7, -5, 12), '', sizeStyle='mini', alignment='left')
                cell.name.getNSTextField().setTextColor_(MasterColor)

    def updateMatrix(self, notification=None):
        axesGrid = self.axesGrid['horizontal'], self.axesGrid['vertical']
        self.currentGlyph = currentGlyph = self.getCurrentGlyph(notification)
        if currentGlyph is not None:
            self.w.glyphTitle.name.set(currentGlyph)
        elif currentGlyph is None:
            self.w.glyphTitle.name.set('No current glyph')
        self.placeGlyphMasters(currentGlyph, axesGrid)
        self.makeGlyphInstances(axesGrid)

    def placeGlyphMasters(self, glyphName, axesGrid):
        availableFonts = AllFonts()
        masters = self.masters
        mutatorMasters = []
        rawMasters = []
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        matrix = self.w.matrix
        masterGlyph = None

        for matrixMaster in masters:
            spot = matrixMaster
            masterFont = spot.getFont()
            ch, j = spot
            i = getValueForKey(ch)
            matrixSpot = self.matrixSpots[spot.getSpotKey()]

            if (masterFont in availableFonts) and (glyphName is not None) and (glyphName in masterFont):
                if i <= nCellsOnHorizontalAxis and j <= nCellsOnVerticalAxis:
                    l = Location(**matrixSpot.getWeightsAsDict('horizontal', 'vertical'))
                    masterGlyph = makePreviewGlyph(masterFont[glyphName])
                    if masterGlyph is not None:
                        mutatorMasters.append((l, masterGlyph.toMathGlyph()))
                        rawMasters.append(masterFont[glyphName])
            elif (masterFont not in availableFonts):
                masters.remove(matrixMaster)

            if i < nCellsOnHorizontalAxis and j < nCellsOnVerticalAxis:
                cell = getattr(matrix, spot.getSpotKey())
                cell.glyphView.setGlyph(masterGlyph)
                if masterGlyph is not None:
                    cell.glyphView.getNSView().setContourColor_(MasterColor)
                    cell.masterMask.show(True)
                    fontName = ' '.join([masterFont.info.familyName, masterFont.info.styleName])
                    cell.name.set(fontName)
                elif masterGlyph is None:
                    cell.glyphView.getNSView().setContourColor_(BlackColor)
                    cell.masterMask.show(False)
                    cell.name.set('')

        self.mutatorMasters = mutatorMasters
        self.rawMasters = rawMasters

    def makeGlyphInstances(self, axesGrid):

        instanceTime = []

        mutatorMasters = self.mutatorMasters
        masterSpots = [master.get() for master in self.masters]
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        matrix = self.w.matrix
        instanceGlyphs = None

        # start = time()
        # count = 0

        if mutatorMasters:

            try:
                if areComponentsCompatible(self.rawMasters):
                    bias, mutator = buildMutator(mutatorMasters)
                else:
                    # components are not compatible
                    mutator = None
            except:
                # import traceback
                # traceback.print_exc()
                mutator = None

            for i in range(nCellsOnHorizontalAxis):
                ch = getKeyForValue(i)

                for j in range(nCellsOnVerticalAxis):

                    if (ch, j) not in masterSpots:

                        matrixSpot = self.matrixSpots['%s%s'%(ch, j)]

                        if mutator is not None:
                            instanceLocation = Location(**matrixSpot.getWeightsAsDict('horizontal', 'vertical'))
                            instanceStart = time()
                            instanceGlyph = RGlyph()
                            iGlyph = mutator.makeInstance(instanceLocation)
                            instanceGlyph = RGlyph()
                            instanceGlyph.fromMathGlyph(iGlyph)
                            instanceStop = time()
                            instanceTime.append((instanceStop-instanceStart)*1000)
                        else:
                            instanceGlyph = self.errorGlyph

                        cell = getattr(matrix, '%s%s'%(ch, j))
                        cell.glyphView.setGlyph(instanceGlyph)
    #                     count += 1

        # stop = time()
        # if count:
        #     wholeTime = (stop-start)*1000
        #     print('made %s instances in %0.3fms, average: %0.3fms' % (count, wholeTime, wholeTime/count))

    def generationSheet(self, sender):

        readableCoord = None
        incomingSpot = None

        if hasattr(sender, 'spot'):
            if hasattr(self.w, 'spotSheet'):
                self.w.spotSheet.close()
            incomingSpot = sender.spot
            ch, j = incomingSpot
            readableCoord = '%s%s'%(ch.upper(), j+1)

        hAxis, vAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        self.w.generateSheet = Sheet((500, 275), self.w)
        generateSheet = self.w.generateSheet

        generateSheet.tabs = Tabs((15, 12, -15, -15), ['Fonts','Glyphs','Report'])
        font = generateSheet.tabs[0]
        glyph = generateSheet.tabs[1]
        report = generateSheet.tabs[2]

        font.guide = TextBox((10, 7, -10, 22),
            u'A1, B2, C4 — A, C (whole columns) — 1, 5 (whole lines) — * (everything)',
            sizeStyle='small')
        font.headerBar = HorizontalLine((10, 25, -10, 1))
        font.spotsListTitle = TextBox((10, 40, 70, 17), 'Locations')
        font.spots = EditText((100, 40, -10, 22))
        if readableCoord is not None:
            font.spots.set(readableCoord)

        font.sourceFontTitle = TextBox((10, 90, -280, 17), 'Source font (naming & groups)', sizeStyle='small')
        font.sourceFontBar = HorizontalLine((10, 110, -280, 1))
        font.sourceFont = PopUpButton((10, 120, -280, 22), [fontName(master.getFont()) for master in self.masters], sizeStyle='small')

        font.interpolationOptions = TextBox((-250, 90, -10, 17), 'Interpolate', sizeStyle='small')
        font.optionsBar = HorizontalLine((-250, 110, -10, 1))
        font.glyphs = CheckBox((-240, 120, -10, 22), 'Glyphs', value=True, sizeStyle='small')
        font.fontInfos = CheckBox((-240, 140, -10, 22), 'Font info', value=True, sizeStyle='small')
        font.kerning = CheckBox((-120, 120, -10, 22), 'Kerning', value=True, sizeStyle='small')
        font.groups = CheckBox((-120, 140, -10, 22), 'Copy Groups', value=True, sizeStyle='small')

        font.openUI = CheckBox((10, -48, -10, 22), 'Open generated fonts', value=True, sizeStyle='small')
        font.report = CheckBox((10, -28, -10, 22), 'Generation report', value=False, sizeStyle='small')

        font.yes = Button((-170, -30, 160, 20), 'Generate font(s)', self.getGenerationInfo)
        font.yes.id = 'font'
        font.no = Button((-250, -30, 75, 20), 'Cancel', callback=self.cancelGeneration)

        glyph.guide = TextBox((10, 7, -10, 22), u'A1, B2, C4, etc.', sizeStyle='small')
        glyph.headerBar = HorizontalLine((10, 25, -10, 1))
        glyph.spotsListTitle = TextBox((10, 40, 70, 17), 'Location')
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        glyph.spot = ComboBox((100, 40, 60, 22), ['%s%s'%(getKeyForValue(i).upper(), j+1) for i in range(nCellsOnHorizontalAxis) for j in range(nCellsOnVerticalAxis)])
        if readableCoord is not None:
            glyph.spot.set(readableCoord)
        glyph.glyphSetTitle = TextBox((10, 72, 70, 17), 'Glyphs')
        glyph.glyphSet = ComboBox(
            (100, 72, -10, 22),
            [
            'abcdefghijklmnopqrstuvwxyz',
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            '01234567890'
            ])
        glyph.targetFontTitle = TextBox((10, 104, 70, 17), 'To font')
        fontList = [fontName(font) for font in AllFonts()]
        fontList.insert(0, 'New font')
        glyph.targetFont = PopUpButton((100, 104, -10, 22), fontList)
        glyph.suffixTile = TextBox((10, 140, 50, 20), 'Suffix')
        glyph.suffix = EditText((100, 136, 100, 22))

        glyph.yes = Button((-170, -30, 160, 20), 'Generate glyph(s)', self.generateGlyphSet)
        glyph.yes.id = 'glyph'
        if incomingSpot is not None:
            glyph.yes.spot = incomingSpot
        glyph.no = Button((-250, -30, 75, 20), 'Cancel', callback=self.cancelGeneration)

        report.options = RadioGroup((10, 5, -10, 40), ['Report only', 'Report and mark glyphs'], isVertical=False)
        report.options.set(0)
        report.markColors = Group((10, 60, -10, -40))
        report.markColors.title = TextBox((0, 5, -10, 20), 'Mark glyphs', sizeStyle='small')
        report.markColors.bar = HorizontalLine((0, 25, 0, 1))
        report.markColors.compatibleTitle = TextBox((0, 35, 150, 20), 'Compatible')
        report.markColors.compatibleColor = ColorWell(
            (170, 35, -0, 20),
            color=getExtensionDefaultColor('interpolationMatrix.compatibleColor', fallback=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3,0.8,0,.9)))
        report.markColors.incompatibleTitle = TextBox((0, 60, 150, 20), 'Incompatible')
        report.markColors.incompatibleColor = ColorWell(
            (170, 60, -0, 20),
            color=getExtensionDefaultColor('interpolationMatrix.incompatibleColor', fallback=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9,0.1,0,1)))
        report.markColors.mixedTitle = TextBox((0, 85, 150, 20), 'Mixed compatibility')
        report.markColors.mixedColor = ColorWell(
            (170, 85, -0, 20),
            color=getExtensionDefaultColor('interpolationMatrix.mixedColor', fallback=NSColor.colorWithCalibratedRed_green_blue_alpha_(.6,.7,.3,.5)))
        report.yes = Button((-170, -30, 160, 20), 'Generate Report', self.getGenerationInfo)
        report.yes.id = 'report'
        report.no = Button((-250, -30, 75, 20), 'Cancel', callback=self.cancelGeneration)

        generateSheet.open()

    def getGenerationInfo(self, sender):

        _ID = sender.id
        generateSheet = self.w.generateSheet
        generateSheet.close()

        if _ID == 'font':
            if hasattr(generateSheet, 'tabs'):
                fontTab = generateSheet.tabs[0]
            elif hasattr(generateSheet, 'font'):
                fontTab = generateSheet.font
            spotsList = []

            if len(self.masters):
                availableFonts = AllFonts()
                mastersList = fontTab.sourceFont.getItems()
                sourceFontIndex = fontTab.sourceFont.get()
                sourceFontName = mastersList[sourceFontIndex]
                sourceFont = [master.getFont() for master in self.masters if fontName(master.getFont()) == sourceFontName and master.getFont() in availableFonts]

                generationInfos = {
                    'sourceFont': sourceFont,
                    'interpolateGlyphs': fontTab.glyphs.get(),
                    'interpolateKerning': fontTab.kerning.get(),
                    'interpolateFontInfos': fontTab.fontInfos.get(),
                    'addGroups': fontTab.groups.get(),
                    'openFonts': fontTab.openUI.get(),
                    'report': fontTab.report.get()
                }

                spotsInput = fontTab.spots.get()
                spotsList = self.parseSpotsList(spotsInput)

                if (spotsList is None):
                    print('Interpolation matrix — at least one location is required.')
                    return

                # print(['%s%s'%(getKeyForValue(i).upper(), j+1) for i, j in spotsList])

            masterLocations = self.getMasterLocations()

            for spot in spotsList:
                i, j = spot
                ch = getKeyForValue(i)
                pickedCell = getattr(self.w.matrix, '%s%s'%(ch, j))
                pickedCell.selectionMask.show(False)
                self.generateInstanceFont(spot, masterLocations, generationInfos)

        elif _ID == 'report':
            reportTab = generateSheet.tabs[2]

            compatibleColor = reportTab.markColors.compatibleColor.get()
            incompatibleColor = reportTab.markColors.incompatibleColor.get()
            mixedColor = reportTab.markColors.mixedColor.get()

            setExtensionDefaultColor('interpolationMatrix.incompatibleColor', incompatibleColor)
            setExtensionDefaultColor('interpolationMatrix.compatibleColor', compatibleColor)
            setExtensionDefaultColor('interpolationMatrix.mixedColor', mixedColor)

            reportInfos = {
                'markGlyphs': bool(reportTab.options.get()),
                'compatibleColor': colorToTuple(compatibleColor),
                'incompatibleColor': colorToTuple(incompatibleColor),
                'mixedColor': colorToTuple(mixedColor)
            }

            self.generateCompatibilityReport(reportInfos)

        delattr(self.w, 'generateSheet')

    def parseSpotsList(self, inputSpots):

        axesGrid = self.axesGrid['horizontal'], self.axesGrid['vertical']
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        inputSpots = inputSpots.split(',')
        masterSpots = [master.getRaw() for master in self.masters]
        spotsToGenerate = []

        if inputSpots[0] == '':
            return
        elif inputSpots[0] == '*':
            return [(i, j) for i in range(nCellsOnHorizontalAxis) for j in range(nCellsOnVerticalAxis) if (i,j) not in masterSpots]
        else:
            for item in inputSpots:
                parsedSpot = self.parseSpot(item, axesGrid)
                if parsedSpot is not None:
                    parsedSpot = list(set(parsedSpot) - set(masterSpots))
                    spotsToGenerate += parsedSpot
            return spotsToGenerate

    def parseSpot(self, spotName, axesGrid):
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        s = re.search('([a-zA-Z](?![0-9]))|([a-zA-Z][0-9][0-9]?)|([0-9][0-9]?)', spotName)
        if s:
            letterOnly = s.group(1)
            letterNumber = s.group(2)
            numberOnly = s.group(3)

            if numberOnly is not None:
                lineNumber = int(numberOnly) - 1
                if lineNumber < nCellsOnVerticalAxis:
                    return [(i, lineNumber) for i in range(nCellsOnHorizontalAxis)]

            elif letterOnly is not None:
                columnNumber = getValueForKey(letterOnly.lower())
                if columnNumber is not None and columnNumber < nCellsOnHorizontalAxis:
                    return [(columnNumber, j) for j in range(nCellsOnVerticalAxis)]

            elif letterNumber is not None:
                letter = letterNumber[:1]
                number = letterNumber[1:]
                columnNumber = getValueForKey(letter.lower())
                try:
                    lineNumber = int(number) - 1
                except:
                    return
                if columnNumber is not None and columnNumber < nCellsOnHorizontalAxis and lineNumber < nCellsOnVerticalAxis:
                    return [(columnNumber, lineNumber)]
        return

    def cancelGeneration(self, sender):
        self.w.generateSheet.close()
        delattr(self.w, 'generateSheet')

    def getMasterLocations(self):
        masters = self.masters
        matrixSpots = self.matrixSpots
        masterLocations = []
        for matrixMaster in masters:
            spotKey = matrixMaster.getSpotKey()
            masterFont = matrixMaster.getFont()
            masterMatrixSpot = matrixSpots[spotKey]
            l = Location(**masterMatrixSpot.getWeightsAsDict('horizontal', 'vertical'))
            masterLocations.append((l, masterFont))
        return masterLocations

    def generateInstanceFont(self, spot, masterLocations, generationInfos):

        if generationInfos['sourceFont']:

            start = time()
            report = []

            doGlyphs = bool(generationInfos['interpolateGlyphs'])
            doKerning = bool(generationInfos['interpolateKerning'])
            doFontInfos = bool(generationInfos['interpolateFontInfos'])
            addGroups = bool(generationInfos['addGroups'])
            doReport = bool(generationInfos['report'])
            UI = bool(generationInfos['openFonts'])

            try:
                masters = self.masters
                baseFont = generationInfos['sourceFont'][0]
                newFont = None
                folderPath = None
                s = re.search('(.*)/(.*)(.ufo)', baseFont.path)
                if s is not None:
                    folderPath = s.group(1)

                masterFonts = [master.getFont() for master in masters]

                i, j = spot
                ch = getKeyForValue(i)
                spotKey = '%s%s'%(ch, j)
                matrixSpot = self.matrixSpots[spotKey]
                instanceLocation = Location(**matrixSpot.getWeightsAsDict('horizontal', 'vertical'))
                instanceName = '%s%s'%(ch.upper(), j+1)

                progress = ProgressWindow('Generating instance %s%s'%(ch.upper(), j+1), parentWindow=self.w)
                report.append(u'\n*** Generating instance %s ***\n'%(instanceName))

                # Build fontx
                if (doGlyphs == True) or (doKerning == True) or (doFontInfos == True) or (addGroups == True):

                    if hasattr(RFont, 'showUI') or (not hasattr(RFont, 'showUI') and (folderPath is not None)):
                        newFont = RFont(showUI=False)
                    elif not hasattr(RFont, 'showUI') and (folderPath is None):
                        newFont = RFont()
                    newFont.info.familyName = baseFont.info.familyName
                    newFont.info.styleName = '%s%s'%(ch.upper(), j+1)
                    try:
                        newFont.glyphOrder = baseFont.glyphOrder
                    except:
                        try:
                            newFont.glyphOrder = baseFont.lib['public.glyphOrder']
                        except:
                            try:
                                newFont.lib['public.glyphOrder'] = baseFont.lib['public.glyphOrder']
                            except:
                                try:
                                    newFont.lib['public.glyphOrder'] = baseFont.glyphOrder
                                except:
                                    pass
                    if folderPath is not None:
                        instancesFolder = u'%s%s'%(folderPath, '/matrix-instances')
                        if not os.path.isdir(instancesFolder):
                            os.makedirs(instancesFolder)
                        folderPath = instancesFolder
                        path = '%s/%s-%s%s'%(folderPath, newFont.info.familyName, newFont.info.styleName, '.ufo')
                    interpolatedGlyphs = []
                    interpolatedInfo = None
                    interpolatedKerning = None
                    interpolationReports = []

                    report.append(u'+ Created new font')

                # interpolate font infos

                if doFontInfos == True:
                    infoMasters = [(infoLocation, masterFont.info.toMathInfo()) for infoLocation, masterFont in masterLocations]
                    try:
                        bias, iM = buildMutator(infoMasters)
                        instanceInfo = iM.makeInstance(instanceLocation)
                        newFont.info.fromMathInfo(instanceInfo)
                        report.append(u'+ Successfully interpolated font info')
                    except:
                        report.append(u'+ Couldn’t interpolate font info')

                # interpolate kerning

                if doKerning == True:
                    kerningMasters = [(kerningLocation, MathKerning(masterFont.kerning)) for kerningLocation, masterFont in masterLocations]
                    try:
                        bias, kM = buildMutator(kerningMasters)
                        instanceKerning = kM.makeInstance(instanceLocation)
                        instanceKerning.extractKerning(newFont)
                        report.append(u'+ Successfully interpolated kerning')
                        if addGroups == True:
                            for key, value in baseFont.groups.items():
                                newFont.groups[key] = value
                            report.append(u'+ Successfully transferred groups')
                    except:
                        report.append(u'+ Couldn’t interpolate kerning')

                # filter compatible glyphs

                glyphList, strayGlyphs = self.compareGlyphSets(masterFonts)

                if doGlyphs == True:

                    incompatibleGlyphs = self.interpolateGlyphSet(instanceLocation, glyphList, masterLocations, newFont)

                    report.append(u'+ Successfully interpolated %s glyphs'%(len(newFont)))
                    report.append(u'+ Couldn’t interpolate %s glyphs'%(len(incompatibleGlyphs)))

                if (newFont is not None) and hasattr(RFont, 'showUI') and (folderPath is None) and UI:
                    newFont.autoUnicodes()
                    try:
                        newFont.round()
                    except TypeError:
                        # font.round() is broken in RF Version 3.2b (built 1808302356)
                        pass
                    newFont.showUI()
                elif (newFont is not None) and (folderPath is not None):
                    newFont.autoUnicodes()
                    try:
                        newFont.round()
                    except TypeError:
                        # font.round() is broken in RF Version 3.2b (built 1808302356)
                        pass
                    newFont.save(path)
                    report.append(u'\n—> Saved font to UFO at %s\n'%(path))
                    if UI:
                        f = RFont(path)
                elif (newFont is not None):
                    print('Couldn’t save font to UFO.')
            except:
                import traceback
                traceback.print_exc()
                print('Couldn’t finish generating, something happened…')
                return
            finally:
                progress.close()

                if doReport:
                    print('\n'.join(report))

            # stop = time()
            # print('generated in %0.3f' % ((stop-start)*1000))

    def generateGlyphSet(self, sender):

        incomingSpot = None
        if hasattr(sender, 'spot'):
            incomingSpot = sender.spot

        generateSheet = self.w.generateSheet
        generateSheet.close()
        glyphTab = generateSheet.tabs[1]
        axesGrid = self.axesGrid['horizontal'], self.axesGrid['vertical']
        masters = self.masters

        targetFontNameIndex = glyphTab.targetFont.get()
        targetFontName = glyphTab.targetFont.getItems()[targetFontNameIndex]

        cmap = masters[0].getFont().getCharacterMapping()
        glyphList = splitText(glyphTab.glyphSet.get(), cmap)
        spot = self.parseSpot(glyphTab.spot.get(), axesGrid)
        if spot is not None and len(spot):
            spot = spot[0]

        suffix = glyphTab.suffix.get()

        if spot is not None:
            progress = ProgressWindow('Generating glyphs', parentWindow=self.w)
            i, j = spot
            ch = getKeyForValue(i)
            spotKey = '%s%s'%(ch, j)
            matrixSpot = self.matrixSpots[spotKey]
            instanceLocation = Location(**matrixSpot.getWeightsAsDict('horizontal', 'vertical'))
            masterLocations = self.getMasterLocations()
            if targetFontName == 'New font':
                targetFont = RFont(showUI=False)
            else:
                targetFont = AllFonts().getFontsByFamilyNameStyleName(*targetFontName.split(' > '))
            self.interpolateGlyphSet(instanceLocation, glyphList, masterLocations, targetFont, suffix)
            targetFont.showUI()
            progress.close()

        if incomingSpot is not None:
            ch, j = incomingSpot
            pickedCell = getattr(self.w.matrix, '%s%s'%(ch, j))
            pickedCell.selectionMask.show(False)

    def interpolateGlyphSet(self, instanceLocation, glyphSet, masters, targetFont, suffix=None):

        incompatibleGlyphs = []

        for glyphName in glyphSet:
            masterGlyphs = [(masterLocation, masterFont[glyphName].toMathGlyph()) for masterLocation, masterFont in masters]
            masterUnicodes = set(masterFont[glyphName].unicode for masterLocation, masterFont in masters)
            masterRawGlyphs = [masterFont[glyphName] for masterLocation, masterFont in masters]

            if len(masterUnicodes) == 1:
                masterUnicode = masterUnicodes.pop()
            else:
                masterUnicode = None
            if areComponentsCompatible(masterRawGlyphs):
                try:
                    bias, gM = buildMutator(masterGlyphs)
                    newGlyph = RGlyph()
                    instanceGlyph = gM.makeInstance(instanceLocation)
                    if suffix is not None:
                        glyphName += suffix
                    newGlyph.fromMathGlyph(instanceGlyph)
                    assert glyphName is not None
                    newGlyph.name = glyphName
                    newGlyph = targetFont.insertGlyph(newGlyph, glyphName)
                    targetFont[glyphName].unicode = masterUnicode
                except:
                    incompatibleGlyphs.append(glyphName)
            else:
                incompatibleGlyphs.append(glyphName)

        return incompatibleGlyphs

    def compareGlyphSets(self, fonts):

        fontKeys = [set(font.keys()) for font in fonts]
        commonGlyphsList = set()
        strayGlyphs = set()
        for i, keys in enumerate(fontKeys):
            if i == 0:
                commonGlyphsList = keys
                strayGlyphs = keys
            elif i > 0:
                commonGlyphsList = commonGlyphsList & keys
                strayGlyphs = strayGlyphs - keys
        return list(commonGlyphsList), list(strayGlyphs)

    def generateCompatibilityReport(self, reportInfo):

        markGlyphs = reportInfo['markGlyphs']
        compatibleColor = reportInfo['compatibleColor']
        incompatibleColor = reportInfo['incompatibleColor']
        mixedCompatibilityColor = reportInfo['mixedColor']

        title = 'Generating report'
        if markGlyphs:
            title += ' & marking glyphs'
        progress = ProgressWindow(title, parentWindow=self.w)

        try:

            masterFonts = [master.getFont() for master in self.masters]
            glyphList, strayGlyphs = self.compareGlyphSets(masterFonts)
            digest = []
            interpolationReports = []
            incompatibleGlyphs = 0

            for glyphName in glyphList:

                refMasterFont = masterFonts[0]
                refMasterGlyph = refMasterFont[glyphName]

                for masterFont in masterFonts[1:]:

                    firstGlyph = refMasterFont[glyphName]
                    secondGlyph = masterFont[glyphName]
                    firstGlyph.mark = None
                    secondGlyph.mark = None
                    try:
                        compatible, report = firstGlyph.isCompatible(secondGlyph)
                    except:
                        report = u'Compatibility check error'
                        compatible == False

                    if compatible == False:

                        names = '%s <X> %s'%(fontName(refMasterFont), fontName(masterFont))
                        reportID = (names, report)
                        if reportID not in interpolationReports:
                            digest.append(names)
                            digest += [u'– %s'%(reportLine) for reportLine in report]
                            digest.append('\n')
                            interpolationReports.append(reportID)
                            incompatibleGlyphs += 1

                        if markGlyphs:
                            if firstGlyph.mark == compatibleColor:
                               firstGlyph.mark = mixedCompatibilityColor
                            elif firstGlyph.mark != compatibleColor and firstGlyph.mark != mixedCompatibilityColor:
                                firstGlyph.mark = incompatibleColor
                            secondGlyph.mark = incompatibleColor

                    elif compatible == True:

                        if markGlyphs:
                            if firstGlyph.mark == incompatibleColor or firstGlyph.mark == mixedCompatibilityColor:
                               firstGlyph.mark = mixedCompatibilityColor
                               secondGlyph.mark = mixedCompatibilityColor
                            else:
                                firstGlyph.mark = compatibleColor
                                secondGlyph.mark = compatibleColor

        finally:
            progress.close()

        print('\n*   Compatible glyphs: %s'%(len(glyphList) - incompatibleGlyphs))
        print('**  Incompatible glyphs: %s'%(incompatibleGlyphs))
        print('*** Stray glyphs: %s\n– %s\n'%(len(strayGlyphs),u'\n– '.join(list(strayGlyphs))))
        print('\n'.join(digest))

    def glyphPreviewCellSize(self, posSize, axesGrid):
        x, y, w, h = posSize
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = axesGrid
        w -= 50-nCellsOnHorizontalAxis
        h -= 50
        cellWidth = w / nCellsOnHorizontalAxis
        cellHeight = h / nCellsOnVerticalAxis
        return cellWidth, cellHeight

    def setSpotRatio(self, sender):
        ch, j = sender.spot
        spotKey = '%s%s'%(ch, j)
        matrixSpot = self.matrixSpots[spotKey]
        masterSpotKeys = [master.getSpotKey() for master in self.masters]
        cell = getattr(self.w.matrix, spotKey)
        hWeight, vWeight = matrixSpot.getWeights()
        newHweight = self.parseWeightValue(cell.locationHvalue.get())
        newVweight = self.parseWeightValue(cell.locationVvalue.get())
        if newHweight is not None: hWeight = newHweight
        elif newHweight is None: cell.locationHvalue.set(str(int(hWeight)))
        if newVweight is not None: vWeight = newVweight
        elif newVweight is None: cell.locationVvalue.set(str(int(vWeight)))
        if spotKey in masterSpotKeys:
            matrixSpot.setWeights((hWeight, vWeight))
            self.reallocateWeights()
        elif spotKey not in masterSpotKeys:
            matrixSpot.shiftWeights((hWeight, vWeight))
        self.updateMatrix()

    def reallocateWeights(self, masterSpotKeys=None):

        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        matrixSpots = self.matrixSpots
        masters = self.masters

        if len(masters) <= 1:

            self.matrixSpots = {}

            for i in range(nCellsOnHorizontalAxis):
                ch = getKeyForValue(i)

                for j in range(nCellsOnVerticalAxis):
                    spotKey = '%s%s'%(ch, j)
                    cell = getattr(self.w.matrix, spotKey)
                    matrixSpot = MatrixSpot((i, j))
                    matrixSpot.setWeights(((i+1)*100, (j+1)*100))
                    weights = matrixSpot.getWeights()
                    cell.locationHvalue.set('%0.0f'%(weights[0]))
                    cell.locationVvalue.set('%0.0f'%(weights[1]))
                    self.matrixSpots[spotKey] = matrixSpot

        elif len(masters) > 1:

            if masterSpotKeys is None:
                masterSpotKeys = [master.getSpotKey() for master in masters]
            hMutatorMasters = []
            vMutatorMasters = []
            for master in masters:
                masterSpotKey = master.getSpotKey()
                mi, mj = master.getRaw()
                mhl = Location(horizontal=mi)
                mvl = Location(vertical=mj)
                hWeight, vWeight = matrixSpots[masterSpotKey].getWeights()
                hMutatorMasters.append((mhl, hWeight))
                vMutatorMasters.append((mvl, vWeight))

            for i in range(nCellsOnHorizontalAxis):
                ch = getKeyForValue(i)
                hb, hm = buildMutator(hMutatorMasters)
                vb, vm = buildMutator(vMutatorMasters)

                for j in range(nCellsOnVerticalAxis):
                    spotKey = '%s%s'%(ch, j)
                    if spotKey not in masterSpotKeys:
                        cell = getattr(self.w.matrix, spotKey)
                        spot = matrixSpots[spotKey]
                        if hm is not None:
                            lh = Location(horizontal=i)
                            instanceHweight = hm.makeInstance(lh)
                        if vm is not None:
                            lv = Location(vertical=j)
                            instanceVweight = vm.makeInstance(lv)
                        spot.setWeights((instanceHweight, instanceVweight))
                        weights = spot.getWeights()
                        cell.locationHvalue.set('%0.0f'%(weights[0]))
                        cell.locationVvalue.set('%0.0f'%(weights[1]))
            self.matrixSpots = matrixSpots

    def parseWeightValue(self, value):
        try: value = float(value)
        except: value = None
        return value

    def pickSpot(self, sender):
        spot = sender.spot
        ch, j = spot
        masters = self.masters
        masterSpots = [master.get() for master in masters]
        axesGrid = self.axesGrid['horizontal'], self.axesGrid['vertical']
        matrix = self.w.matrix
        font = None

        self.setSpotSelection(matrix, spot, axesGrid)

        self.w.spotSheet = Sheet((500, 250), self.w)
        spotSheet = self.w.spotSheet
        spotSheet.mastersTitle = TextBox((20, 20, -20, 21), 'Available masters', sizeStyle='small')
        spotSheet.fontList = FontList((20, 40, -20, 110), AllFonts(), allowsMultipleSelection=False)
        if spot not in masterSpots:
            spotSheet.yes = Button((-140, -40, 120, 20), 'Place Master', callback=self.changeSpot)
            spotSheet.generate = Button((20, -40, 180, 20), 'Generate Instance %s%s'%(ch.upper(), j+1), callback=self.generationSheet)
            spotSheet.generate.spot = spot
            if len(masters) <= 1:
                spotSheet.generate.enable(False)
            elif len(masters) > 1:
                spotSheet.generate.enable(True)
        elif spot in masterSpots:
            spotSheet.clear = Button((20, -40, 130, 20), 'Remove Master', callback=self.clearSpot)
            spotSheet.yes = Button((-140, -40, 120, 20), 'Change Master', callback=self.changeSpot)
        spotSheet.no = Button((-230, -40, 80, 20), 'Cancel', callback=self.keepSpot)
        for buttonName in ['clear', 'yes', 'no', 'generate']:
            if hasattr(spotSheet, buttonName):
                button = getattr(spotSheet, buttonName)
                button.spot = spot
        spotSheet.open()

    def changeSpot(self, sender):
        spot = sender.spot
        ch, j = sender.spot
        fontsList = self.w.spotSheet.fontList.get()
        selectedFontIndex = self.w.spotSheet.fontList.getSelection()[0]
        font = fontsList[selectedFontIndex]
        self.w.spotSheet.close()
        delattr(self.w, 'spotSheet')
        pickedCell = getattr(self.w.matrix, '%s%s'%(ch, j))
        pickedCell.selectionMask.show(False)
        i = getValueForKey(ch)
        l = MatrixMaster(spot, font)
        self.masters.append(l)
        self.updateMatrix()

    def clearSpot(self, sender):
        spot = (ch, j) = sender.spot
        self.w.spotSheet.close()
        delattr(self.w, 'spotSheet')
        pickedCell = getattr(self.w.matrix, '%s%s'%(ch, j))
        pickedCell.selectionMask.show(False)
        pickedCell.masterMask.show(False)
        pickedCell.glyphView.getNSView().setContourColor_(BlackColor)
        pickedCell.name.set('')
        for matrixMaster in self.masters:
            masterSpot = matrixMaster.get()
            if spot == masterSpot:
                self.masters.remove(matrixMaster)
                break
        if not len(self.masters):
            self.clearMatrix()
        self.mutator = None
        self.reallocateWeights()
        self.updateMatrix()

    def setSpotSelection(self, matrix, spot, axesGrid):
        for i in range(axesGrid[0]):
            ch = getKeyForValue(i)
            for j in range(axesGrid[1]):
                cell = getattr(matrix, '%s%s'%(ch, j))
                if (ch,j) == spot:
                    cell.selectionMask.show(True)
                else:
                    cell.selectionMask.show(False)

    def keepSpot(self, sender):
        ch, j = sender.spot
        self.w.spotSheet.close()
        delattr(self.w, 'spotSheet')
        pickedCell = getattr(self.w.matrix, '%s%s'%(ch, j))
        pickedCell.selectionMask.show(False)

    def addColumn(self, sender):
        gridMax = self.gridMax
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        nCellsOnHorizontalAxis += 1
        if nCellsOnHorizontalAxis > gridMax:
            nCellsOnHorizontalAxis = gridMax
        self.buildMatrix((nCellsOnHorizontalAxis, nCellsOnVerticalAxis))
        self.axesGrid['horizontal'] = nCellsOnHorizontalAxis
        self.reallocateWeights()
        self.updateMatrix()

    def removeColumn(self, sender):
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        mastersToRemove = []

        if (nCellsOnHorizontalAxis > 3) or \
           ((nCellsOnHorizontalAxis <= 3) and (nCellsOnHorizontalAxis > 1) and (nCellsOnVerticalAxis >= 3)):
            nCellsOnHorizontalAxis -= 1

        self.buildMatrix((nCellsOnHorizontalAxis, nCellsOnVerticalAxis))


        self.axesGrid['horizontal'] = nCellsOnHorizontalAxis
        for matrixMaster in self.masters:
            ch, j = matrixMaster.get()
            i = getValueForKey(ch)
            if i >= nCellsOnHorizontalAxis:
                mastersToRemove.append(matrixMaster)
        for matrixMaster in mastersToRemove:
            self.masters.remove(matrixMaster)
        self.mutator = None
        self.reallocateWeights()
        self.updateMatrix()

    def addLine(self, sender):
        gridMax = self.gridMax
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        nCellsOnVerticalAxis += 1
        if nCellsOnVerticalAxis > gridMax:
            nCellsOnVerticalAxis = gridMax
        self.buildMatrix((nCellsOnHorizontalAxis, nCellsOnVerticalAxis))
        self.axesGrid['vertical'] = nCellsOnVerticalAxis
        self.reallocateWeights()
        self.updateMatrix()

    def removeLine(self, sender):
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']
        mastersToRemove = []

        if (nCellsOnVerticalAxis > 3) or \
           ((nCellsOnVerticalAxis <= 3) and (nCellsOnVerticalAxis > 1) and (nCellsOnHorizontalAxis >= 3)):
            nCellsOnVerticalAxis -= 1

        self.buildMatrix((nCellsOnHorizontalAxis, nCellsOnVerticalAxis))
        self.axesGrid['vertical'] = nCellsOnVerticalAxis
        for matrixMaster in self.masters:
            ch, j = matrixMaster.get()
            if j >= nCellsOnVerticalAxis:
                mastersToRemove.append(matrixMaster)
        for matrixMaster in mastersToRemove:
            self.masters.remove(matrixMaster)
        self.mutator = None
        self.reallocateWeights()
        self.updateMatrix()

    def clearMatrix(self, sender=None):
        self.masters = []
        self.matrixSpots = {}
        self.mutator = None
        matrix = self.w.matrix
        nCellsOnHorizontalAxis, nCellsOnVerticalAxis = self.axesGrid['horizontal'], self.axesGrid['vertical']

        for i in range(nCellsOnHorizontalAxis):
            ch = getKeyForValue(i)
            for j in range(nCellsOnVerticalAxis):
                cell = getattr(matrix, '%s%s'%(ch, j))
                cell.glyphView.setGlyph(None)
                cell.glyphView.getNSView().setContourColor_(BlackColor)
                cell.selectionMask.show(False)
                cell.masterMask.show(False)
                cell.name.set('')

    def saveMatrix(self, sender):
        pathToSave = putFile(title='Save interpolation matrix', fileName='matrix.txt', fileTypes=['txt'])
        if pathToSave is not None:
            masters = self.masters
            matrixSpots = self.matrixSpots
            axesGrid = self.axesGrid
            matrixTextValues = []
            for master in masters:
                masterSpotKey = master.getSpotKey()
                matrixSpot = matrixSpots[masterSpotKey]
                matrixTextValues.append(':'.join([masterSpotKey, matrixSpot.getWeightsAsString(), master.getFontPath()]))
            posSize = self.w.getPosSize()
            matrixTextValues = ['Matrix Interpolation File\n','%s,%s\n'%(axesGrid['horizontal'], axesGrid['vertical']), ','.join([str(value) for value in posSize]),'\n', str(self.currentGlyph),'\n',','.join(matrixTextValues)]
            matrixTextForm = ''.join(matrixTextValues)
            with open(pathToSave, 'w') as f:
                f.write(matrixTextForm)

    def loadMatrixFile(self, sender):
        pathToLoad = getFile(fileTypes=['txt'], allowsMultipleSelection=False, resultCallback=self.loadMatrix, parentWindow=self.w)

    def loadMatrix(self, pathToLoad):
        if pathToLoad is not None:
            self.matrixSpots = {}
            self.reallocateWeights()
            with open(pathToLoad[0], 'r') as f:
                matrixTextForm = f.read()
            matrixValues = matrixTextForm.split('\n')
            if matrixValues and matrixValues[0] == 'Matrix Interpolation File':
                limits = tuple(matrixValues[1].split(','))
                axesGrid = int(limits[0]), int(limits[1])
                posSize = tuple([float(value) for value in matrixValues[2].split(',')])
                self.w.resize(posSize[2], posSize[3])
                self.axesGrid['horizontal'], self.axesGrid['vertical'] = axesGrid
                self.buildMatrix(axesGrid)
                self.currentGlyph = matrixValues[3]
                masterSpots = [value.split(':') for value in matrixValues[4].split(',')]
                if len(masterSpots):
                    masters = []
                    matrixSpots = self.matrixSpots
                    fontsToOpen = []
                    for masterSpot in masterSpots:
                        if len(masterSpot) > 1:
                            spotKey = masterSpot[0]
                            fontPath = masterSpot[-1]
                            spot = splitSpotKey(spotKey)
                            if (spot is not None) and (fontPath is not None):
                                f = [font for font in AllFonts() if font.path == fontPath]
                                if not len(f):
                                    f = RFont(fontPath)
                                elif len(f):
                                    f = f[0]
                                if len(masterSpot) > 2:
                                    cell = getattr(self.w.matrix, spotKey)
                                    weights = masterSpot[1].split('/')
                                    matrixSpot = MatrixSpot(spot)
                                    hWeight, vWeight = float(weights[0]), float(weights[1])
                                    matrixSpot.setWeights((hWeight, vWeight))
                                    matrixSpots[spotKey] = matrixSpot
                                    cell.locationHvalue.set(str(int(hWeight)))
                                    cell.locationVvalue.set(str(int(vWeight)))
                                masters.append(MatrixMaster(spot, f))
                    self.matrixSpots = matrixSpots
                    self.masters = masters
                self.reallocateWeights()
                self.updateMatrix()
            else:
                print('not a valid matrix file')


    def changeGlyph(self, sender):
        inputText = sender.get()
        try:
            charMap = CurrentFont().getCharacterMapping()
            glyphs = splitText(inputText, charMap)
            if len(glyphs):
                self.currentGlyph = glyphs[0]
                self.updateMatrix()
        except:
            return

    def getCurrentGlyph(self, notification=None):
        if notification is not None:
            currentGlyph = CurrentGlyph()
            if currentGlyph is None:
                currentGlyphName = self.currentGlyph
            elif currentGlyph is not None:
                currentGlyphName = currentGlyph.name
            return currentGlyphName
        return self.currentGlyph

    def windowResize(self, info):
        axesGrid = (nCellsOnHorizontalAxis, nCellsOnVerticalAxis) = (self.axesGrid['horizontal'], self.axesGrid['vertical'])
        posSize = info.getPosSize()
        cellXSize, cellYSize = self.glyphPreviewCellSize(posSize, axesGrid)
        matrix = self.w.matrix

        for i in range(nCellsOnHorizontalAxis):
            ch = getKeyForValue(i)
            for j in range(nCellsOnVerticalAxis):
                cell = getattr(matrix, '%s%s'%(ch,j))
                cell.setPosSize((i*cellXSize, j*cellYSize, cellXSize, cellYSize))
                cell.locationHvalue.setPosSize((-40, (cellYSize/2)-8, 36, 16))
                cell.locationVvalue.setPosSize(((cellXSize/2)-18, -18, 36, 16))

    def windowClose(self, notification):
        self.w.unbind('close', self.windowClose)
        self.w.unbind('resize', self.windowResize)
        removeObserver(self, "currentGlyphChanged")
        removeObserver(self, "mouseUp")
        removeObserver(self, "keyUp")
        removeObserver(self, "fontDidClose")

InterpolationMatrixController()
