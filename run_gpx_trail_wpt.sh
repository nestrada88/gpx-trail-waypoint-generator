#!/usr/bin/env bash

set -euo pipefail

# ==========================================================
# COLORS
# ==========================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ==========================================================
# DEFAULTS
# ==========================================================

IMAGE_NAME="${IMAGE_NAME:-gpx-trail-wpt}"
CONTAINER_NAME="gpx-runner"

DISTANCE_METHOD="auto"
REBUILD_IMAGE=false

GPX_FILE=""
TRAIL_PREFIX=""
STEP_KM=""

# ==========================================================
# USAGE
# ==========================================================

usage() {
  echo -e "${YELLOW}GPX Trail Waypoint Generator Wrapper${NC}"
  echo
  echo "Usage:"
  echo "  $0 --file <GPX_FILE> --prefix <PREFIX> --step <KM> [options]"
  echo
  echo "Required:"
  echo "  --file FILE              GPX track file"
  echo "  --prefix PREFIX          3-letter waypoint prefix"
  echo "  --step KM                Distance between markers (km)"
  echo
  echo "Options:"
  echo "  --distance-method METHOD auto|geodesic|haversine"
  echo "  --rebuild                Force Docker image rebuild"
  echo "  -h, --help               Show this help"
  echo
  echo "Example:"
  echo "  $0 --file trail.gpx --prefix HIK --step 1.5 --distance-method haversine"
  exit 1
}

# ==========================================================
# ARGUMENT PARSING
# ==========================================================

PARSED_ARGS=$(getopt \
  --options h \
  --longoptions help,file:,prefix:,step:,distance-method:,rebuild \
  --name "$0" \
  -- "$@"
)

if [[ $? -ne 0 ]]; then
  usage
fi

eval set -- "$PARSED_ARGS"

while true; do
  case "$1" in

    --file)
      GPX_FILE="$2"
      shift 2
      ;;

    --prefix)
      TRAIL_PREFIX="$2"
      shift 2
      ;;

    --step)
      STEP_KM="$2"
      shift 2
      ;;

    --distance-method)
      DISTANCE_METHOD="$2"
      shift 2
      ;;

    --rebuild)
      REBUILD_IMAGE=true
      shift
      ;;

    -h|--help)
      usage
      ;;

    --)
      shift
      break
      ;;

    *)
      usage
      ;;
  esac
done

# ==========================================================
# VALIDATION
# ==========================================================

if [[ -z "$GPX_FILE" || -z "$TRAIL_PREFIX" || -z "$STEP_KM" ]]; then
  echo -e "${RED}Error:${NC} Missing required arguments."
  usage
fi

if [ ! -f "$GPX_FILE" ]; then
  echo -e "${RED}Error:${NC} File '$GPX_FILE' not found."
  exit 2
fi

if [[ ! "$TRAIL_PREFIX" =~ ^[A-Z]{3}$ ]]; then
  echo -e "${RED}Error:${NC} Prefix must be exactly three uppercase letters."
  exit 3
fi

if ! [[ "$STEP_KM" =~ ^[0-9]+([.][0-9]+)?$ ]] || (( $(echo "$STEP_KM <= 0" | bc -l) )); then
  echo -e "${RED}Error:${NC} Step size must be a positive number."
  exit 4
fi

if [[ "$DISTANCE_METHOD" != "auto" && "$DISTANCE_METHOD" != "geodesic" && "$DISTANCE_METHOD" != "haversine" ]]; then
  echo -e "${RED}Error:${NC} Invalid distance method."
  echo "Allowed values: auto | geodesic | haversine"
  exit 5
fi

# ==========================================================
# DOCKER CONFIG
# ==========================================================

MOUNT_DIR="$(dirname "$(realpath "$GPX_FILE")")"
GPX_FILENAME="$(basename "$GPX_FILE")"
OUTPUT_FILE="${GPX_FILENAME%.gpx}_${STEP_KM}_wpt.gpx"

# ==========================================================
# DOCKER IMAGE CHECK
# ==========================================================

if [[ "$REBUILD_IMAGE" == true ]]; then

  echo -e "${YELLOW}Rebuilding Docker image '${IMAGE_NAME}'...${NC}"
  docker build -t "$IMAGE_NAME" .

else

  if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo -e "${GREEN}Docker image '${IMAGE_NAME}' not found. Building...${NC}"
    docker build -t "$IMAGE_NAME" .
  else
    echo -e "${GREEN}Using existing Docker image '${IMAGE_NAME}'.${NC}"
  fi

fi

# ==========================================================
# RUN CONTAINER
# ==========================================================

echo -e "${GREEN}Running GPX processing container...${NC}"

docker run --rm \
  --name "$CONTAINER_NAME" \
  -v "$MOUNT_DIR":/app/data \
  "$IMAGE_NAME" \
  /app/data/"$GPX_FILENAME" \
  "$TRAIL_PREFIX" \
  "$STEP_KM" \
  --distance-method "$DISTANCE_METHOD"

# ==========================================================
# DONE
# ==========================================================

echo -e "${GREEN}Success!${NC}"
echo -e "  📁 Output file: ${YELLOW}${OUTPUT_FILE}${NC}"
echo -e "  ⚙️  Distance method: ${DISTANCE_METHOD}"
echo -e "  🧭 Waypoints include:"
echo -e "     Trail Head, Trail End,"
echo -e "     Highest, Lowest,"
echo -e "     Halfway, and every ${STEP_KM} km."
