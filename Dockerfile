FROM osgeo/gdal:latest
WORKDIR /workdir
COPY requirements.txt .

RUN apt update && apt install -y python3-pip

RUN python3.8 -m pip install -r requirements.txt
