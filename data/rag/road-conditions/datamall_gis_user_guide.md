# LTA DataMall GIS User Guide

- Source URL: https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_GIS_User_Guide.pdf
- Retrieved At: 2026-04-14T10:30:55.052057+00:00
- Source Type: pdf
- Raw File: C:/Users/victo/OneDrive/Desktop/SkyMirror/data/sources/singapore-official/raw/datamall_gis_user_guide.pdf
- Notes: Official DataMall geospatial documentation PDF.

## Page 1

an
LTA Open Data Initiative

Geospatial User Guide
& Specifications

Version 1.4
28 July 2023

## Page 2

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

Document Change Log

Version
No.
Change Details Release Date
1.0 First release. 07 April 2015
1.1 Added section on GDAL. 13 April 2015
1.2 Added Covered Linkway and Footpath 19 April 2015
1.3 Updated Lane Marking documentation 15 April 2021
1.4 Removed Emergency Gate
Added Kerbline, Parking Standard Zone, School Zone, Silver Zone,
Traffic Count, Train Station, Train Station Exit Point and Vehicular
Bridge / Flyover / Underpass.
28 July 2023

## Page 3

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

TABLE OF CONTENTS
1. ABOUT GEOSPATIAL SHAPEFILES ................................................................................................................... 5
2. GEOSPATIAL DATA ABSTRACTION LIBRARY .............................................................................................. 7
2.1 INSTALLING GDAL................................................................................................................................................ 7
2.2 USING GDAL ........................................................................................................................................................... 8
2.3 LANGUAGE SUPPORT FOR GDAL .................................................................................................................. 8
3 GEOSPTIAL DATASET SPECIFICATIONS ........................................................................................................ 9
3.1 Arrow Marking .................................................................................................................................................... 12
3.2 Bollard .................................................................................................................................................................... 15
3.3 Bus Stop Location .............................................................................................................................................. 16
3.4 Control Box .......................................................................................................................................................... 18
3.5 Convex Mirrors ................................................................................................................................................... 19
3.6 Covered Linkway ................................................................................................................................................ 20
3.7 Cycling Path ......................................................................................................................................................... 21
3.8 Detector Loops ................................................................................................................................................... 22
3.9 ERP Gantry ........................................................................................................................................................... 23
3.10 Footpath ............................................................................................................................................................... 24
3.11 Guard Rail ............................................................................................................................................................. 25
3.12 Kerbline ................................................................................................................................................................. 25
3.13 Lamp Posts ........................................................................................................................................................... 26
3.14 Lane Markings .................................................................................................................................................... 27
3.15 Parking Standard Zone .................................................................................................................................... 43
3.16 Passenger Pickup Bay ...................................................................................................................................... 44
3.17 Pedestrian Overhead Bridge / Underpass ................................................................................................ 45
3.18 Railings .................................................................................................................................................................. 48
3.19 Retaining Walls ................................................................................................................................................... 49

## Page 4

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.20 Road Crossing ..................................................................................................................................................... 49
3.21 Road Hump .......................................................................................................................................................... 50
3.22 Road Section Lines ............................................................................................................................................ 50
3.23 School Zone ......................................................................................................................................................... 51
3.24 Silver Zone ............................................................................................................................................................ 51
3.25 Speed Regulating Strips ................................................................................................................................... 52
3.26 Street Paint ........................................................................................................................................................... 53
3.27 Taxi Stand .............................................................................................................................................................. 54
3.28 Traffic Count ......................................................................................................................................................... 57
3.29 Traffic Light ........................................................................................................................................................... 60
3.30 Traffic Sign ............................................................................................................................................................ 61
3.31 Train Station ......................................................................................................................................................... 63
3.32 Train Station Exit Point ...................................................................................................................................... 63
3.33 Vehicular Bridge / Flyover / Underpass ....................................................................................................... 63
3.34 Word Markings ................................................................................................................................................... 64

## Page 5

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

1. ABOUT GEOSPATIAL SHAPEFILES

Geospatial data is a collection of vector data – points, lines or polygons. These
typically represent physical entities or locations, such as a bus stop (point), a road
(line) or even a constituency (polygon).
LTA’s geospatial datasets are encoded as ESRI shapefiles. This is a proprietary
standard which allows points, lines and polygons to be easily defined and accessed.
For full technical definition on ESRI shapefiles, you may refer to:
http://www.esri.com/library/whitepapers/pdfs/shapefile.pdf
Each geospatial dataset is a zip archive that contains 8 separate files (refer to Figure
1.1 below) that needs to be processed to extract spatial information that you will use
in your development and/or research purposes.

Figure 1.1: a set of files that forms one geospatial dataset

Some standard spatial information that you will find in geospatial data include:

Attribute Description
properties A collection of attribute-value pairs that uniquely describes each point,
line, or polygon, and therefore varies across datasets. Specifications for
each geospatial dataset may be found in Section 3 of this User Guide.
geometry type The type of vector feature: point, line, polygon.
coordinate
(LTA’s geospatial data
are under SVY21 system)
Latitude-longitude pair(s) that define the
location of the vector features. Points are
defined by a pair; lines are defined by two pairs,
while polygons are defined by a set of pairs.

## Page 6

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

{ "type": "Feature", "properties": { "TYP_CD": "B",
"BEARG_NUM": 5.000000, "BEARG_NUM_": null,
"TYP_CD_DES": "B - St\/Lt Turn" }, "geometry": { "type": "Point",
"coordinates": [ 41850.949109771288931, 36418.658599032089114 ]
} }
{ "type": "Feature", "properties": { "SHAPE_LEN": 16.304837 },
"geometry": { "type": "LineString", "coordinates": [ [
32550.172179710119963, 36959.311381651088595 ], [
32562.167958052828908, 36970.354434320703149 ] ] } }
{ "type": "Feature", "properties": { "SHAPE_AREA": 64.584770,
"SHAPE_LEN": 60.029009 }, "geometry": { "type": "Polygon",
"coordinates": [ [ [ 31597.694404867579578,
39221.842085721094918 ], [ 31574.630992666363454,
39206.476809959007369 ], [ 31573.391504064809851,
39208.309705873791245 ], [ 31596.26679 4926454168,
39223.839076249976642 ], [ 31597.694404867579578,
39221.842085721094918 ] ] ] } }

The following are sample spatial information you may find in the geospatial datasets.
Dataset: Arrow Marking (Point)

Dataset: Passenger Pickup Bay (Line)

Dataset: Covered Linkway (Polygon)

The next section of this User Guide carries instructions to guide you in extracting
attributes from the geospatial datasets. The rest of this User Guide carries the
specifications for all datasets that you may refer to better understand the attributes.

## Page 7

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

2. GEOSPATIAL DATA ABSTRACTION LIBRARY

The Geospatial Data Abstraction Library (GDAL) is a very handy tool to convert
ESRI shapefiles into readable formats such as GeoJSON, and to convert between
geospatial coordinate systems, such as from SVY21 to the common WGS84 for our
usual latitude-longitude values.

2.1 INSTALLING GDAL

FOR WINDOWS
Step 1: Go to www.gisinternals.com/sdk/ and click on “Stable Releases”
Step 2: Under “MSVC 2013”, select the correct architecture for your computer (win32
for 32-bit, x64 for 64-bit) and click on the relevant link to the download files.
Step 3: Download the core installation file, with description “Generic installer for the
GDAL core components”.
Step 4: Run the .msi file to install GDAL
Step 5: Run the GDAL command prompt under Start Menu > All Programs > GDAL.
You’re good to go!

FOR MAC OS X
Step 1: If you don’t already have it, install Homebrew (www.brew.sh)
Step 2: In your open Terminal window, type
>> brew install gdal
Step 3: Verify your installation
>> which ogr2ogr
This should print “/usr/local/bin/ogr2ogr”.
You’re good to go!

FOR UBUNTU LINUX
Step 1: Open your Terminal window and type
>> sudo apt-get install gdal-bin
Step 2: Verify your installation by typing
>> which ogr2ogr
This should print “/usr/bin/ogr2ogr” or similar.
You’re good to go!

## Page 8

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

2.2 USING GDAL

Open your Linux/OSX Terminal (or the GDAL Command Prompt for Windows) to
start using GDAL. Here are a few sample commands to get you started.

Obtaining metadata description of a shapefile:
>> ogrinfo <shapefile>.shp –al -so

Converting a Shapefile to WGS84 GeoJSON:
>> ogr2ogr -f GeoJSON –t_srs WGS84 <jsonFileName>.json
<shapefile>.shp

To see full list of output file formats:
>> ogr2ogr –-long-usage

2.3 LANGUAGE SUPPORT FOR GDAL

GDAL supports multiple languages and can be directly embedded in your
applications. Links for instructions on installation and usage can be found below.

Language URL
Python http://trac.osgeo.org/gdal/wiki/GdalOgrInPython
C# / .NET http://trac.osgeo.org/gdal/wiki/GdalOgrInCsharp
Ruby http://trac.osgeo.org/gdal/wiki/GdalOgrInRuby
Java http://trac.osgeo.org/gdal/wiki/GdalOgrInJava
R http://trac.osgeo.org/gdal/wiki/GdalOgrInR
Perl http://trac.osgeo.org/gdal/wiki/GdalOgrInPerl

## Page 9

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3 GEOSPTIAL DATASET SPECIFICATIONS

Geospatial Datasets
(Total 34) Description

1

Arrow Marking
A point representation of an arrow painted on the road
surface to advise motorists on the direction of traffic
flow.

2

Bollard
A point representation of a strong thick post erected on
streets to deter vehicles from passing through. It is also
used as markers on road divider or as safety barriers
along bus bay or side of roads.
The split arrow bollard is captured under the ‘Traffic
Sign’ dataset.
3 Bus Stop Location A point representation to indicate the position where
buses should stop to pick up or drop off passengers.

4

Control Box
A point representation of a box containing an electronic
device to control traffic lights, street lighting, ERP and
traffic camera (J-eyes).

5

Convex Mirror
A point representation of a mirror placed at street
corner where visibility is poor, to assist motorists when
making a turn at blind spots.

6

Covered Linkway
A polygon representation of a covered passage
designated for pedestrian use to link up with other
commuter facilities.
7 Cycling Path A line representation of an intra-town path designated
for cyclists. Excludes park connectors.

8

Detector Loop
A polygon representation of an electronic loop on the
road surface at strategic locations to detect traffic
movements for traffic control purposes.

9

ERP Gantry
A line representation of a raised metallic structure
spanning across a carriageway to support electronic
equipment for ERP.
10 Footpath A line representation of a path designated for
pedestrian use.
11 Guard Rail A line representation of a safety barrier to prevent
vehicles from veering off the road or carriageway.
12 Kerbline A line representation of the edges of roads.
13 Lamp Post A point representation of a pole for mounting street
lighting.

## Page 10

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

14 Lane Marking A line representation painted on the road surface to
guide motorists along the carriageway.
15 Parking Standards
Zone

A polygon representation to indicate the location of a LTA
parking standard zone.

16

Passenger Pickup Bay
A line representation of an area along the side of road
designated for vehicles to pick up or drop off
passengers. Pick-up bays are normally found at
MRT/LRT stations and commercial sites.

17
Pedestrian Overhead
Bridge / Underpass
A polygon representation of a raised or underground
structure to be used by pedestrians to cross a road or
canal.

18

Railing
A line representation of a metallic barrier to separate
between two areas; for instance, between two road
carriageways, along edges of road or embankment.
19 Retaining Wall A line representation of a wall that supports the
adjacent soil from erosion or landslide.
20 Road Crossing A line representation of a designated location for
pedestrians to cross the road.

21

Road Hump
A line representation of a raised section across a road
to reduce the speed of vehicles. Road Humps are
painted over with distinctive diagonal alternate black
and yellow strips. It is usually preceded by a “HUMP
AHEAD” marking on the road in the direction of the
traffic flow.
22 Road Section Line A line representation with information on road name
and road code.
23 School Zone Polygon representation of School Zones.
24 Silver Zone Polygon representation of Silver Zones.

25 Speed Regulating
Strip
A line representation of raised painted strips across a
road to reduce the speed of vehicles when approaching
a bend or near heavy pedestrian traffic.

26

Street Paint
A polygon representation of a section of the road
paved in red to warn motorists that they are entering a
zone where school children may be crossing roads.
27 Taxi Stand A point representation to indicate the position where
taxis should stop to pickup or drop off passengers.
28 Traffic Count Provides information of classified vehicle volume for turn
movements at junctions. The turn movements volumes
are recorded in 15 minutes intervals.

29

Traffic Light
A point representation of lights consisting of signal
aspects such as ground, overhead, green filter arrow,
beacons, etc to control traffic flow.

## Page 11

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

30 Traffic Sign A point representation for traffic signs that help
regulate, warn, guide or inform all road users.
31 Train Station A point representation to indicate the location of
the MRT station.
32 Train Station Exit Point A point representation to indicate the location of a train
station exit point.
33 Vehicular Bridge /
Flyover / Underpass
Vehicular Bridge / Flyover / Underpass

34

Word Marking
A point representation of a word painted on the road
surface to give motorists advance information on
approaching facilities or traffic related devices. (e.g.
HUMP AHEAD, SLOW etc.)

## Page 12

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.1 Arrow Marking
Filename ArrowMarking.shp

Description A point representation of an arrow
painted on the road surface to advise
motorists on the direction of traffic flow.

Attribute Format:

Field Name Data
Type
Size Precision Scale Allow
Null
Value Description
TYP_CD String 4 0 0 No A, B, C, D,
E, F, G, H, I,
J, K, L, M,
N, O
Please see Note 1
BEARG_NUM Double 8 38 8 No Bearing. Please see Note 2
LVL_NUM Short 2 4 0 No Level of road where feature exists
2 At-grade (ground level)
8 1st level depressed road
9 1st level elevated road
7 2nd level depressed road
10 2nd level elevated road

## Page 13

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

Notes:
1. List of TYP_CD:

2. The bearing should correspond with the bearing of each individual road. For example, if
the bearing of the road is 97 degrees, then the bearing of arrow markings A is 97
degrees and the bearing of arrow markings B is 277 degrees respectively.

## Page 14

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3. Arrow Marking co-ordinate is the midpoint at the base of the arrow in the direction of
the traffic flow.

For example,
a) Type C (straight / right turn shared arrow): one arrow only, hence only one point (x1,
y1) required.

b) Types G (left converging arrow) & H (right converging arrow): two arrows, hence two
points (x1, y1) and (x2, y2) are required.

## Page 15

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.2 Bollard

Filename Bollard.shp
Description A point representation of a strong thick
post erected on streets to deter vehicles
from passing through. It is also used as
markers on road divider or as safety
barriers along bus bay or side of roads.
The split arrow bollard is captured under
the ‘Traffic Sign’ dataset.

## Page 16

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.3 Bus Stop Location

Filename BusStop.shp
Description A point representation to indicate the
position where buses should stop to pick
up or drop off passengers.
Attribute Format:

Notes:

1. Records the co-ordinates of the BUS STOP POLE.

2. BUS_STOP_N – The five digit bus stop identification number that is displayed on the bus
stop pole eg.50071 or 27301 as shown on new design. To record A as 1, Z as 9, B as 2, Y
as 8 etc if the identification number contains alphabets.
Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
BUS_STOP_N String 65 0 0 No Please see Note 2
BUS_ROOF_N String 10 0 0 No Please see Note 3
LOC_DESC Text 255 0 0 No Location Description as shown
on the bus stop pole

## Page 17

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3. BUS_ROOF_N – B-Series Number showed on the side of bus shelter roof eg. B01.

## Page 18

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.4 Control Box

Filename ControllerBox.shp
Description A point representation of a box
containing an electronic device to control
traffic lights, street lighting, ERP and
traffic camera (J-eyes).

## Page 19

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.5 Convex Mirrors

Filename ConvexMirror.shp
Description A point representation of a mirror placed at
street corner where visibility is poor, to
assist motorists when making a turn at blind
spots.
Attribute Format:

Notes:
1. Record the co -ordinate of the pole on
which the CONVEX MIRROR is
mounted.

2. Bearing of convex mirror

Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
BEARG_NUM Double 8 38 8 No Bearing. Please see Note 2

## Page 20

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.6 Covered Linkway

Filename CoveredLinkWay.shp
Description A polygon representation of a covered passage
designated for pedestrian use to link up with
other commuter facilities.
Notes:
The linkway shall be represented by a polygon outlining the structure as seen from aerial
view. The outline shall correspond to the outer edge of the roof of the covered linkway, as
shows on example below by points 1, 2, 3, 4, 5, 6, 7, 8 & 9.

## Page 21

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.7 Cycling Path

Filename LTACyclingTrail.shp
Description A line representation of an intra -town
path designated for cyclists. Excludes
park connectors.
Attribute Format:

Field Name

Name

Hyperlink

Description

Data
Type

String

String

String

Sample Value

Sembawang Cycling
Path

www.mytransport.sg

/content/mytransport

/home/cycling.html

Intra-town Cycling
Path in Sembawang
Estate

Description

Name of the cycling path

URL to MyTransport
Cycling Page

Description of the cycling
path.

## Page 22

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.8 Detector Loops

Filename DetectorLoop.shp
Description A polygon representation of an electronic
loop on the road surface at strategic
locations to detect traffic movements for
traffic control purposes.

## Page 23

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.9 ERP Gantry

Filename Gantry.shp
Type Line
Description A line representation of a raised metallic
structure spanning across a carriageway
to support electronic equipment for ERP.
Attribute Format:

Notes:
1. List of TYP_CD:
TYP_CD Description
P ERP

Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
TYP_CD String 4 0 0 No Please see Note 1
P ERP
TYP_CD_DES Text 12 0 0 No ERP

## Page 24

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.10 Footpath

Filename Footpath.shp
Description A line representation of a path designated for pedestrian
use.
Notes:
1. The centre line of the FOOTPATH is to be captured.

## Page 25

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.11 Guard Rail

Filename GuardRail.shp
Description A line representation of a safety barrier
to prevent vehicles from veering off the
road or carriageway.

3.12 Kerbline
Filename Kerbline.shp
Description A line representation of the edges of
roads.

## Page 26

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.13 Lamp Posts

Filename LampPost.shp
Description A point representation of a pole for
mounting street lighting.
Attribute Format:

Note:
1. A lamp post with its lamp post number 27.
Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
LAMPPOST_N String 20 0 0 The number that is displayed
on the lamp post. Please see
Note 1.

## Page 27

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.14 Lane Markings

Filename LaneMarking.shp
Description A line representation painted on the road
surface to guide motorists along the
carriageway.
Attribute Format:
Field Name Data

Type
Siz
e
Precision Scal
e
Allow

Null
Value Description

TYP_CD

String

4

0

0

No
Please see Note 5
A
A1
A2
A3
A4
A5
B
B1
C
D
E
F
G
H
I
J
K
L
M

## Page 28

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

N
O
P
Q Multi-headed arrow
marking

R Bus zone
S Continuous red line
for full day bus lane

S1 Dotted red line for full
day bus lane

T Turning pocket
U Pedestrian Ahead
marking

V Vibraline
X Traffic calming
marking

Y Mandatory give way
to buses exiting
yellow box

Notes:
1. LANE MARKINGS within all Road are required to be collected and identified

## Page 29

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

accordingly.
2. All coordinates captured shall be based on the centre of the lines.
3. If part of LANE MARKING is a single line and the other part is a double line, record as
two separate records (see example below).

x1,y1 x2,y2
x3,y3 x4,y4
4. For Yellow Box Junction, bus zone and turning pocket capture all the vertices forming
the out lines.
5. List of TYP_ CD:
TYP_CD Colour Description
A White These white
lines are used to
indicate the
edge of the
carriageway
adjacent to
auxiliary lanes e.
g. Exclusive right
/ left turn lanes
at junctions, lay -
bys, bus bay etc
1 m x 1 m x 0.1 m
A1 Yellow These yellow
lines are used
along bus lanes
to indicate a
break for use by
other turning
vehicles
1 m x 1 m x 0.1 m

## Page 30

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

A2 White These white
lines are use to
indicate the
edge of the
carriageway
adjacent to
auxiliary lanes
e.g. Exclusive
right/left turn
lanes at
acceleration/dec
eleration lanes
along
expressways. It
is also known as
speed change
lane marking
1 m x 1 m x 0.2 m
A3 Yellow These broken
yellow lines are
used along bus
lane at junction
with side road
1 m x 1 m x 0.3 m
A4 White These broken
white lines are
used to
demarcate
signalised
pedestrian
crossing lines
0.2mx 0.3mx0.2m

## Page 31

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

A5 White These broken
white lines are
used for guiding
motorist across
a wide/ skewed
junction
1m x 3m x
0.1m

B White These white
lines are used as
lane marking
between lanes
2 m x 4 m x 0.1 m

## Page 32

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

B1 White These white
lines are used as
lane marking
between lanes
on expressway
only
2 m x 10 m x 0.1 m
C White These white
lines are used as
lane markings at
light controlled
intersection and
along the
approaches
at/before the
stop line.
(Generally 7 to
10 marks are
painted)
4 m x 2 m x 0.1 m

## Page 33

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

D White-
Double
Two parallel
white lines
indicate that
traffic
approaching
these lines is to
give way to
oncoming traffic
either on the left
or right
1 m x 1 m x 0.1 m
E White These white
lines are used as
centre lines on a
two-way
carriageway
2.75 m x 2.75 m x 0.15 m

## Page 34

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

F White This continuous
white line is
used as a centre
line on a two-
way carriageway
and also
indicates no
parking on both
sides
Continuous x 0.15 m
G Yellow This continuous
yellow line by
the side of the
carriageway
indicates no
parking from
7.00a.m. to
7.00p.m on that
side of the
carriageway
except Sundays
and public
holidays
Continuous x 0.15 m
H White-
Double
Two parallel
continuous
white lines used
as centre line on
a two-way
carriageway or
between lanes
to indicate no
crossing of the
lines
Continuous x 0.10 m

## Page 35

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

I Yellow-
Double
Two parallel
continuous
yellow lines by
the side of the
carriageway
indicate no
parking at all
times on that
side of the
carriageway
Continuous x 0.10 m
J White This continuous
white line is
used along
expressway
adjacent to
paved shoulder
to indicate the
presence of
shoulder or
adjacent to
centre divider to
indicate edge
line. These are
also painted at
pedestrian
crossings to
Continuous x 0.30 m

## Page 36

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

indicate the area
where
pedestrians can
cross.

K White These zig zag
white line are
used to indicate
approaching
zebra crossing.
They also
indicate no
crossing and no
parking at area
where these
lines are painted
Zig Zag x 0.1m
L Yellow This continuous
yellow line is
used as bus lane
marking
Continuous x 0.30 m

## Page 37

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

M White This continuous
white line is
used as stop
lines & edge
lines painted
next to the
centre divider
kerbs. These are
also painted
along dual 3 -
lane (and above)
roads where
street lightings
are not provided
along the centre
divider.
Continuous x 0.20 m
N Yellow These
continuous
yellow lines are
used for yellow
box junction.
200mm for the
diagonals and
455mm for the
sides
Continuous
O Yellow Single zig zag
yellow line at
the edge of a
road prohibiting
parking at all
times
Zig Zag x 0.1m

## Page 38

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

P Yellow-
Double
Double zig zag
yellow line at
the edge of a
road prohibiting
stopping of
vehicles at all
times unless the
vehicle is
prevented from
proceeding due
to traffic
conditions
Zig Zag x 0.1m
Q White Type Q is for
multi-headed
arrows LANE
MARKING
Continuous

## Page 39

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

R Yellow Type R is for Bus
Zone marking
Continuous
S Red This line is used
as a full day bus
lane marking.
Continuous
S1 Red These lines are
used along bus
lanes to indicate
a break for use
by other turning
vehicles.
Dash

## Page 40

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

T White Type T is for
Turning Pocket
marking
Dash
U White Pedestrian
crossing ahead
marking (PCAM)
As shown

## Page 41

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

V White Type V is for
Vibraline
marking
Continuous
X White Traffic calming
marking
As shown

## Page 42

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

Y Yellow Mandatory
give way to
buses exiting
yellow box

## Page 43

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.15 Parking Standard Zone
Filename ParkingZone.shp
Type Polygon
Description A polygon representation to indicate the
location of a LTA parking standard zone.

## Page 44

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.16 Passenger Pickup Bay

Filename PassengerPickupBay.shp
Type Line
Description A line representation of an area along the
side of road designated for vehicles to
pick up or drop off passengers. Pick -up
bays are normally found at MRT/LRT
stations and commercial sites.
Notes:
1. The span of PICKUP BAY shall be the two end-most points of the bays.

## Page 45

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.17 Pedestrian Overhead Bridge / Underpass

Filename PedestrianOverheadbridge.shp
Type Polygon
Description A polygon representation of a raised or
underground structure to be used by
pedestrians to cross a road or canal.
Attribute Format:

Notes:
1. The PEDESTRIAN OVERHEAD BRIDGE/UNDERPASS shall be represented by a polygon
outlining the structure as seen from aerial view. The outline shall correspond to the
outer edge of the bridge railing and the base of the staircases at either end of the bridge.
Points P1 to P12 need to be captured.

P1 P2 P5 P6

P12 P11 P8 P7

Arial view of a
Pedestrian Overhead Bridge with
staircases at both ends
Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
TYP_CD String 4 0 0 No Please see Note 1
PO Pedestrian Overhead
Bridge
PU Pedestrian Underpass
FB Foot Bridge
BW Broad Walk
PB Pedestrian Bridge

P3 P4

P10 P9

## Page 46

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

2. List of TYP_CD:
TYP_CD Description
PO Pedestrian
Overhead
Bridge

PU Pedestrian
Underpass

FB Foot
Bridge

## Page 47

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

BW Broad
Walk

PB Pedestrian
Bridge

## Page 48

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.18 Railings

Filename Railing.shp
Type Line
Description A line representation of a metallic barrier
to separate between two areas; for
instance, between two road carriageways,
along edges of road or embankment.
Notes:
1. The length of the RAILING is the two end-most points, i.e.

x1,y1 x2,y2

2. The standard gap between two RAILING panels shall be IGNORED and the two railings
panels treated as one continuous span.

a gap between 2 railings
x1,y1 x2,y2

## Page 49

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.19 Retaining Walls

Filename RetainingWall.shp
Type Line
Description A line representation of a wall that
supports the adjacent soil from erosion
or landslide.
Notes:
1. The length of the RETAINING WALL is to be measured along its base.

3.20 Road Crossing

Filename RoadCrossing.shp
Description A line representation of a designated
location for pedestrians to cross the road.

## Page 50

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.21 Road Hump

Filename RoadHump.shp
Description A line representation of a raised section across a road
to reduce the speed of vehicles. Road Humps are
painted over with distinctive diagonal alternate black
and yellow strips. It is usually preceded by a “HUMP
AHEAD” marking on the road in the direction of the
traffic flow.
Notes:
1. The Road Hump span is to be recorded at the centre line of the hump.

(x1,y1)

Direction of Road Hump
traffic flow

(x2,y2) Cente line of Road
Hump in the direction
of traffic flow

3.22 Road Section Lines

Filename RoadSectionLine.shp
Description A line representation with information on
road name and road code.
Attribute Format:
Field Name

RD_CD

RD_CD_DESC

Data Type

Sample Value

Description

String

WAC01Y Road code assigned to road
name

String WATERLOO
CLOSE

Description of the road code

## Page 51

LTA DataMall | GIS User Guide & Specifications Version
1.4 (28 July 2023)

3.23 School Zone

Filename SchoolZone.shp
Description Polygon representation of School Zones.

3.24 Silver Zone

Filename SilverZone.shp
Description Polygon representation of Silver Zones.

## Page 52

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.25 Speed Regulating Strips

Filename SpeedRegulatingStrip.shp
Type Line
Description A line representation of raised painted
strips across a road to reduce the speed
of vehicles when approaching a bend or
near heavy pedestrian traffic.
Notes:
1 Record the centre line of the strip.
2 For a series of SPEED REGULATING STRIPS found on the road, record only the two end-
most STRIPS and join up the two strips with a diagonal line as shown:-

x2,y2 x4,y4
Direction of
Traffic Flow Ending
Strip
Starting x1,y1 x3,y3
Strip

## Page 53

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.26 Street Paint

Filename StreetPaint.shp
Description A polygon representation of a section of
the road paved in red to warn motorists
that they are entering a zone where
school children may be crossing roads.
Notes:
1. Capture all corners of the polygon
depicting the STREET PAINT section.

## Page 54

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.27 Taxi Stand

Filename TaxiStop.shp
Description A point representation to indicate the
position where taxis should stop to
pickup or drop off passengers.
Attribute Format:

Notes:
1) Record the co-ordinate of the TAXI STOP POLE

Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
TYP_CD String 10 0 0 No TSTOP Taxi Stop
TPD Taxi Pick up/Drop off
TSTAND Taxi Stand

## Page 55

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

2) List of TYP_CD:
TYP_CD Description
TSTOP Taxi Stop

TPD Taxi Pick-
up/Drop Off

## Page 56

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

TSTAND Taxi Stand

## Page 57

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.28 Traffic Count

Filename Traffic_Count_Data.gdb
Description Provides information of classified vehicle
volume for turn movements at junctions.
The turn movements volumes are
recorded in 15 minutes intervals.
Description for Traffic Count Data

1. This data is in *.gdb format and will require a GIS software to extract information within
it. The below readme file provided is based on a free and open source QGIS software.

2. The traffic count data provides information of classified vehicle volume for turn
movements at junctions. The turn movements volumes are recorded in 15 minutes
intervals. Most of the traffic count data are for a duration of 2 hours. However, for
some locations, the recorded turn movement volumes may exceed 2 hours.

3. The traffic count data is grouped by junction and in the form of excel spreadsheet.
Within the excel spreadsheet, a location map and passenger car unit (pcu) factor are
also provided.
README How to use the data layer

1. Add the layer to QGIS software (as shown below)

2. Layer added
a. To have a better view, you may consider downloading the “Road Section Line”
layer in DataMall.

## Page 58

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3. Label the location point
a. See step 1 to step 7 below

4. Location point labelled

## Page 59

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

5. Save the data file
a. See step 1 to step 6

6. The count data in excel format is now ready to view in your folder.

## Page 60

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.29 Traffic Light

Filename TrafficSignalAspect.shp
Description A point representation of lights
consisting of signal aspects such as
ground, overhead, green filter arrow,
beacons, etc to control traffic flow.
Attribute Format:
Notes:
1. The bearing of the traffic signal is required and should be within  3 tolerance.

Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
BEARG_NUM Double 8 38 8 No Bearing of traffic signal aspect

Please see Note 1

## Page 61

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.30 Traffic Sign

Filename TrafficSign.shp
Type Point
Description A point representation for traffic signs
that help regulate, warn, guide or inform
all road users.
Attribute Format:

Notes:
1. If traffic sign description does not match any sign in the list, enter ‘O###’, where ### is a
running serial number that uniquely identifies a particular non-standard traffic sign.

2. The co-ordinate of TRAFFIC SIGN should be captured at the horizontal centre of the
sign(s).
Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
TYP_CD String 4 0 0 No Please refer to Note 4 for
Category
BEARG_NUM Double 8 38 8 No Bearing of the traffic sign.

Please see Note 3.
MOUNT_MTD_CD String 1 0 0 No P Traffic sign mounted
on
1 pole
Q Traffic sign mounted
on
2 poles
B Bridge
G Gantry
W Wall
L Lamp Post
S Traffic Signal
X Others

## Page 62

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3. The bearing should follow the flow of traffic except for pedestrian crossing prohibition
(1014) and directional arrow (4006) signs. Their orientation are as shown in diagram
below:

4. Category of Traffic Signs

1001 to 1999 - Prohibitory Traffic Sign
2001 to 2999 - Warning Traffic Sign
3001 to 3999 - Information Traffic Sign
4001 to 4999 - Supplementary Traffic Sign
5001 to 5999 - Mandatory Traffic Sign
6001 to 6999 - Street Traffic Sign
9001 to 9299 - Flyover Traffic Sign
9300 to 9399 - Tunnel Traffic Sign
9400 to 9499 - Underpass Traffic Sign
9500 to 9599 - Viaduct Traffic Sign

## Page 63

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.31 Train Station
Filename RapidTransitSystemStation.shp
Description A point representation to indicate the
location of the MRT station.

3.32 Train Station Exit Point
Filename Train_Station_Exit_Layer.shp
Description A point representation to indicate the
location of a train station exit point.

3.33 Vehicular Bridge / Flyover / Underpass
Filename VehicleOverBridgeUnderpass.shp
Description A polygon representation of a Vehicular
Bridge / Flyover / Underpass.

## Page 64

LTA DataMall | GIS User Guide & Specifications
Version 1.4 (28 July 2023)

3.34 Word Markings

Filename WordMarking.shp
Description A point representation of a word painted
on the road surface to give motorists
advance information on approaching
facilities or traffic related devices. (e.g.
HUMP AHEAD, SLOW etc.)
Attribute Format:

Field Name Data

Type
Size Precision Scale Allow

Null
Value Description
DESC_TXT String 15 0 0 No Record the word (text) of the
marking in the description field.
Please see Note 2
BEARG_NUM Double 8 38 8 No Bearing. Please see Note 2

Notes:
1. Word Marking location is the mid-point of the word marked. E.g. HUMP AHEAD, two
separate POINT records, xx and yy are to be captured.

2. The bearing of the word marking is required.
