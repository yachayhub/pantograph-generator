/**
  Copyright (C) 2012-2021 by Autodesk, Inc.
  All rights reserved.

  Messer plasma post processor configuration.

  $Revision: 43775 8a6a8a924f86fab9397f9d69d17b1e07897a7fe6 $
  $Date: 2022-04-20 16:35:00 $

  FORKID {30798152-1823-4AE6-9D03-894528526F9F}
*/

description = "Messer plasma";
vendor = "Messer";
vendorUrl = "http://www.messer-cs.com/";
legal = "Copyright (C) 2012-2021 by Autodesk, Inc.";
certificationLevel = 2;
minimumRevision = 45702;

longDescription = "Generic post for Messer plasma cutting.";

extension = "txt";
programNameIsInteger = false;
setCodePage("ascii");

capabilities = CAPABILITY_JET;
tolerance = spatial(0.002, MM);

minimumChordLength = spatial(0.25, MM);
minimumCircularRadius = spatial(0.01, MM);
maximumCircularRadius = spatial(1000, MM);
minimumCircularSweep = toRad(0.01);
maximumCircularSweep = toRad(180);
allowHelicalMoves = true;
allowedCircularPlanes = undefined; // allow any circular motion

// user-defined properties
properties = {
  showSequenceNumbers: {
    title      : "Use sequence numbers",
    description: "Use sequence numbers for each block of outputted code.",
    group      : "formats",
    type       : "boolean",
    value      : false,
    scope      : "post"
  },
  sequenceNumberStart: {
    title      : "Start sequence number",
    description: "The number at which to start the sequence numbers.",
    group      : "formats",
    type       : "integer",
    value      : 10,
    scope      : "post"
  },
  sequenceNumberIncrement: {
    title      : "Sequence number increment",
    description: "The amount by which the sequence number is incremented by in each block.",
    group      : "formats",
    type       : "integer",
    value      : 1,
    scope      : "post"
  },
  separateWordsWithSpace: {
    title      : "Separate words with space",
    description: "Adds spaces between words if 'yes' is selected.",
    group      : "formats",
    type       : "boolean",
    value      : true,
    scope      : "post"
  },
  useFeeds: {
    title      : "Use feed",
    description: "Specifies whether feed codes should be output.",
    group      : "preferences",
    type       : "boolean",
    value      : false,
    scope      : "post"
  },
  useCoolant: {
    title      : "Use coolant",
    description: "Specifies whether M7/M8 should be output",
    group      : "preferences",
    type       : "boolean",
    value      : true,
    scope      : "post"
  }
};

// wcs definiton
wcsDefinitions = {
  useZeroOffset: false,
  wcs          : [
    {name:"Standard", format:"G", range:[54, 59]}
  ]
};

var gFormat = createFormat({prefix:"G", width:2, zeropad:true, decimals:0});
var mFormat = createFormat({prefix:"M", width:2, zeropad:true, decimals:0});
var xyzFormat = createFormat({decimals:(unit == MM ? 3 : 4)});
var feedFormat = createFormat({decimals:(unit == MM ? 1 : 2)});
var toolFormat = createFormat({decimals:0, prefix:"T"});
var powerFormat = createFormat({decimals:0});
var secFormat = createFormat({decimals:3, forceDecimal:true}); // seconds - range 0.001-1000

var xOutput = createVariable({prefix:"X"}, xyzFormat);
var yOutput = createVariable({prefix:"Y"}, xyzFormat);
var zOutput = createVariable({prefix:"Z"}, xyzFormat);
var feedOutput = createVariable({prefix:"F"}, feedFormat);
var sOutput = createVariable({prefix:"S", force:true}, powerFormat);
var powerOutput = createVariable({prefix:"G"}, powerFormat);

// circular output
var iOutput = createReferenceVariable({prefix:"I", force:true}, xyzFormat);
var jOutput = createReferenceVariable({prefix:"J", force:true}, xyzFormat);

var gMotionModal = createModal({force:true}, gFormat); // modal group 1 // G0-G3, ...
var gPlaneModal = createModal({onchange:function() {gMotionModal.reset();}}, gFormat); // modal group 2 // G17-19
var gAbsIncModal = createModal({}, gFormat); // modal group 3 // G90-91
var gFeedModeModal = createModal({}, gFormat); // modal group 5 // G93-94
var gUnitModal = createModal({}, gFormat); // modal group 6 // G20-21

var WARNING_WORK_OFFSET = 0;

// collected state
var sequenceNumber;
var currentWorkOffset;

/**
  Writes the specified block.
*/
function writeBlock() {
  if (getProperty("showSequenceNumbers")) {
    writeWords2("N" + sequenceNumber, arguments);
    sequenceNumber += getProperty("sequenceNumberIncrement");
  } else {
    writeWords(arguments);
  }
}

function formatComment(text) {
  return "(" + String(text).replace(/[()]/g, "") + ")";
}

/**
  Output a comment.
*/
function writeComment(text) {
  writeln(formatComment(text));
}

function getPowerMode(section) {
  var mode;
  switch (section.quality) {
  case 0: // auto
    break;
  case 1: // high
    break;
  case 2: // medium
    break;
  case 3: // low
    break;
  default:
    error(localize("Only Cutting Mode Through-auto and Through-high are supported."));
    return 0;
  }
  return mode;
}

function onOpen() {
  if (!getProperty("useFeeds")) {
    feedOutput.disable();
  }
  zOutput.disable();
  if (!getProperty("separateWordsWithSpace")) {
    setWordSeparator("");
  }

  sequenceNumber = getProperty("sequenceNumberStart");

  if (programName) {
    writeComment("%%INFO PartName=" + programName);
  }

  if (programComment) {
    writeComment("Program Comment=" + programComment);
  }

  switch (unit) {
  case IN:
    writeBlock(gUnitModal.format(20));
    break;
  case MM:
    writeBlock(gUnitModal.format(21));
    break;
  }

  writeBlock(gFormat.format(70));
  writeBlock(gAbsIncModal.format(91));
  writeBlock("G92 X0 Y0 Z0");
  writeComment("End Header");
}

function onComment(message) {
  writeComment(message);
}

/** Force output of X, Y, and Z. */
function forceXYZ() {
  xOutput.reset();
  yOutput.reset();
  zOutput.reset();
}

/** Force output of X, Y, Z, and F on next output. */
function forceAny() {
  forceXYZ();
  feedOutput.reset();
}

function onSection() {

  if (currentSection.getType() == TYPE_JET) {
    switch (tool.type) {
    case TOOL_PLASMA_CUTTER:
      break;
    default:
      error(localize("The CNC does not support the required tool/process. Only plasma cutting is supported."));
      return;
    }

    switch (currentSection.jetMode) {
    case JET_MODE_THROUGH:
      break;
    case JET_MODE_ETCHING:
      break;
    case JET_MODE_VAPORIZE:
      break;
    default:
      error(localize("Unsupported cutting mode."));
      return;
    }
  } else {
    error(localize("The CNC does not support the required tool/process. Only plasma cutting is supported."));
    return;
  }

  // wcs
  if (currentSection.workOffset != currentWorkOffset) {
    writeBlock(currentSection.wcs);
    currentWorkOffset = currentSection.workOffset;
  }

  if (isFirstSection()) {
    // home axes
    writeBlock(gFormat.format(162));
    // cancel cutter comp
    writeBlock(gFormat.format(141));
    writeBlock(gFormat.format(237));
    writeBlock("#CS ON [V.E.START_X, V.E.START_Y, 0, 0, 0, V.E.ROTATION]");
    // wait for temprature to reach target
    writeBlock(mFormat.format(190));
  }

  { // pure 3D
    var remaining = currentSection.workPlane;
    if (!isSameDirection(remaining.forward, new Vector(0, 0, 1))) {
      error(localize("Tool orientation is not supported."));
      return;
    }
    setRotation(remaining);
  }

  var initialPosition = getFramePosition(currentSection.getInitialPosition());
  writeBlock(gMotionModal.format(0), xOutput.format(initialPosition.x), yOutput.format(initialPosition.y));

  // insert a basic tool call
  var insertToolCall = isFirstSection() || getPreviousSection().getTool().number != currentSection.getTool().number;
  if (insertToolCall) {
    writeBlock(toolFormat.format(tool.number));
  }
}

function onDwell(seconds) {
  if (seconds > 99999.999) {
    warning(localize("Dwelling time is out of range."));
  }
  seconds = clamp(0.001, seconds, 99999.999);
  writeBlock(gFormat.format(4), "P" + secFormat.format(seconds));
}

var pendingRadiusCompensation = -1;

function onRadiusCompensation() {
  pendingRadiusCompensation = radiusCompensation;
}

function onPower(power) {
  if (power) {
    if (getProperty("useCoolant")) {
      writeBlock(mFormat.format(7));
    }
    writeBlock(powerOutput.format(261));
  } else {
    writeBlock(powerOutput.format(260));
    if (getProperty("useCoolant")) {
      writeBlock(mFormat.format(8));
    }
  }
}
// Variables globales para almacenar las últimas posiciones
var previousX = null;
var previousY = null;
var previousZ = null;

function onRapid(_x, _y, _z) {
  // Calcular las diferencias (incrementos) respecto a la última posición
  var deltaX = _x - previousX;
  var deltaY = _y - previousY;
  var deltaZ = _z - previousZ;

  // Actualizar las posiciones anteriores
  previousX = _x;
  previousY = _y;
  previousZ = _z;

  // Formatear las diferencias para emitirlas
  var x = xOutput.format(deltaX);
  var y = yOutput.format(deltaY);
  var z = zOutput.format(deltaZ);

  if (x || y || z) {
    if (pendingRadiusCompensation >= 0) {
      error(localize("Radius compensation mode cannot be changed at rapid traversal."));
      return;
    }
    writeBlock(gMotionModal.format(0), x, y, z);
    feedOutput.reset();
  }
}

function onLinear(_x, _y, _z, feed) {
  // Asegurarse de que al menos un eje esté en movimiento
  if (pendingRadiusCompensation >= 0) {
    xOutput.reset();
    yOutput.reset();
  }
  
  // Si es la primera vez, inicializa las posiciones previas
  if (previousX === null) previousX = _x;
  if (previousY === null) previousY = _y;
  if (previousZ === null) previousZ = _z;

  // Calcular las diferencias (incrementos) respecto a la última posición
  var deltaX = _x - previousX;
  var deltaY = _y - previousY;
  var deltaZ = _z - previousZ;

  // Actualizar las posiciones anteriores
  previousX = _x;
  previousY = _y;
  previousZ = _z;

  var x = xOutput.format(deltaX); // Formatear el incremento en X
  var y = yOutput.format(deltaY); // Formatear el incremento en Y
  var z = zOutput.format(deltaZ); // Formatear el incremento en Z
  var f = feedOutput.format(feed); // Formatear el feed rate

  if (x || y || z) {
    if (pendingRadiusCompensation >= 0) {
      pendingRadiusCompensation = -1;
      switch (radiusCompensation) {
      case RADIUS_COMPENSATION_LEFT:
        writeBlock(gFormat.format(41), gMotionModal.format(1), x, y, z, f);
        break;
      case RADIUS_COMPENSATION_RIGHT:
        writeBlock(gFormat.format(42), gMotionModal.format(1), x, y, z, f);
        break;
      default:
        writeBlock(gFormat.format(40), gMotionModal.format(1), x, y, z, f);
      }
    } else {
      writeBlock(gMotionModal.format(1), x, y, z, f);
    }
  } else if (f) {
    if (getNextRecord().isMotion()) { // Evitar emitir feed sin movimiento
      feedOutput.reset(); // Forzar el feed en la siguiente línea
    } else {
      writeBlock(gMotionModal.format(1), f);
    }
  }
}

function onCircular(clockwise, cx, cy, cz, x, y, z, feed) {
  if (pendingRadiusCompensation >= 0) {
    error(localize("Radius compensation cannot be activated/deactivated for a circular move."));
    return;
  }

  var start = getCurrentPosition();

  // Calcular los incrementos para los movimientos circulares
  var deltaX = x - previousX;
  var deltaY = y - previousY;
  var deltaZ = z - previousZ;
  var deltaI = cx - start.x;
  var deltaJ = cy - start.y;

  // Actualizar las posiciones anteriores
  previousX = x;
  previousY = y;
  previousZ = z;

  if (isFullCircle()) {
    if (isHelical()) {
      linearize(tolerance);  // Descomponer movimiento helicoidal en movimientos lineales
      return;
    }
    switch (getCircularPlane()) {
    case PLANE_XY:
      writeBlock(gMotionModal.format(clockwise ? 2 : 3), xOutput.format(deltaX), iOutput.format(deltaI, 0), jOutput.format(deltaJ, 0), feedOutput.format(feed));
      break;
    default:
      linearize(tolerance);
    }
  } else {
    switch (getCircularPlane()) {
    case PLANE_XY:
      writeBlock(gMotionModal.format(clockwise ? 2 : 3), xOutput.format(deltaX), yOutput.format(deltaY), zOutput.format(deltaZ), iOutput.format(deltaI, 0), jOutput.format(deltaJ, 0), feedOutput.format(feed));
      break;
    default:
      linearize(tolerance);
    }
  }
}

var mapCommand = {
  COMMAND_STOP: 0,
  COMMAND_END : 2
};

function onCommand(command) {
  switch (command) {
  case COMMAND_POWER_ON:
    return;
  case COMMAND_POWER_OFF:
    return;
  case COMMAND_LOCK_MULTI_AXIS:
    return;
  case COMMAND_UNLOCK_MULTI_AXIS:
    return;
  case COMMAND_BREAK_CONTROL:
    return;
  case COMMAND_TOOL_MEASURE:
    return;
  }

  var stringId = getCommandStringId(command);
  var mcode = mapCommand[stringId];
  if (mcode != undefined) {
    writeBlock(mFormat.format(mcode));
  } else {
    onUnsupportedCommand(command);
  }
}

function onSectionEnd() {
  forceAny();
}

function onClose() {
  writeBlock(gFormat.format(40));
  writeBlock(toolFormat.format(0));
  writeBlock("#CS OFF");
  writeBlock(mFormat.format(30));
}

function setProperty(property, value) {
  properties[property].current = value;
}
