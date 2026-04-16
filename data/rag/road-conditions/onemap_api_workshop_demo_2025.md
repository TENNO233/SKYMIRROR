# OneMap API Workshop Demo 260825

- Source URL: https://www.onemap.gov.sg/apidocs/static/media/OneMap_API_Workshop_Demo_260825.6522ddef4affd370a81a.pdf
- Retrieved At: 2026-04-14T10:30:57.592763+00:00
- Source Type: pdf
- Raw File: C:/Users/victo/OneDrive/Desktop/SkyMirror/data/sources/singapore-official/raw/onemap_api_workshop_demo_2025.pdf
- Notes: Official OneMap API workshop deck served from the OneMap API docs portal.

## Page 1

1© SINGAPORE LAND AUTHORITY LIMITED LAND UNLIMITED SPACE
OneMap Workshop
(26/08/2025)
RESTRICTED / NON-SENSITIVE

## Page 2

2
AGENDA
• Registration/Password Reset
• Basemap
• Authentication
• Search
• Reverse Geocode
• Nearest BusStop/MRT
• Call Rate Limit

## Page 3

3
Confirmation
https://www.onemap.gov.sg/apidocs/registerconfirm

## Page 4

4
Register
https://www.onemap.gov.sg/apidocs/register

## Page 5

5
Forgot Password
https://www.onemap.gov.sg/apidocs/forgetpassword

## Page 6

6
Reset Password

## Page 7

7
• Default
• Original
• Grey
• GreyLite
• Night
• LandLot
BASEMAP
Map Styles

## Page 8

8
• RS256 JWT Token
• Validity for 3 days
● Token is needed for all
endpoints except basemaps
and staticmap api.
AUTHENTICATION
https://www.onemap.gov.sg/apidocs/authentication
https://www.onemap.gov.sg/apidocs/docs/jwttokenupdate

## Page 9

9
AUTHENTICATION
https://www.onemap.gov.sg/apidocs/docs/tokenmanagement

## Page 10

10
SEARCH
https://www.onemap.gov.sg/apidocs/search
How to verify on-boarding Tokenised Search
● Missing Token (Token is yet to be passed in requesting header.)
● Expired Token (Token is passed but has already expired.)
● Invalid Token (JWT Token is not a valid OneMap Token.)

## Page 11

11
MISSING TOKEN
“Authentication token
missing. Please create an
account and generate or
renew your API Token.”

## Page 12

12
EXPIRED TOKEN
“Authentication token
expired. Token are valid for
3 days. Please implement
automatic renewal to
ensure your token remains
valid.”

## Page 13

13
INVALID TOKEN
“Invalid authentication
token. Please register for an
account and provide a valid
API token.”

## Page 14

14
REVERSE GEOCODE
Translates Coordinates to Address.
● location (latitude,longitude)
● addressType [optional]
● buffer (0 to 500m) [optional]

## Page 15

15
NEARBY
Get nearest Bus Stops.
latitude
longitude
radius_in_meters
(0 to 5000m) [optional]

## Page 16

16
NEARBY
Get nearest MRT Stops.
● latitude
● longitude
● radius_in_meters
(0 to 5000m) [optional]

## Page 17

17
CALL RATE LIMIT

## Page 18

18
18
Q&A
RESTRICTED / NON-SENSITIVE 18

## Page 19

19© SINGAPORE LAND
AUTHORITY
DD/MM/YYYY
19
THANK YOU
LIMITED LAND UNLIMITED SPACESLA
RESTRICTED / NON-SENSITIVE
19

## Page 20

20© SINGAPORE LAND
AUTHORITY
DD/MM/YYYY
20
THANK YOU
LIMITED LAND UNLIMITED SPACESLA
RESTRICTED / NON-SENSITIVE
20
