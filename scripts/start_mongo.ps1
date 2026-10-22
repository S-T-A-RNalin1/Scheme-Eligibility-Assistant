# Starts a single-node MongoDB replica set for this project (transactions need a replica set).
# Uses the locally installed MongoDB 8.x server; data lives in .mongo-data next to the project.
$root = Split-Path -Parent $PSScriptRoot
$mongod = (Get-ChildItem "C:\Program Files\MongoDB\Server\*\bin\mongod.exe" | Select-Object -Last 1).FullName
New-Item -ItemType Directory -Force "$root\.mongo-data" | Out-Null
Start-Process -FilePath $mongod -ArgumentList "--replSet rs0 --port 27018 --bind_ip 127.0.0.1 --dbpath `"$root\.mongo-data`" --logpath `"$root\.mongo-data\mongod.log`"" -WindowStyle Hidden
Start-Sleep -Seconds 3
python -c "from pymongo import MongoClient; c=MongoClient('mongodb://127.0.0.1:27018/?directConnection=true'); print(c.admin.command('replSetInitiate', {'_id':'rs0','members':[{'_id':0,'host':'127.0.0.1:27018'}]}) if c.admin.command('hello').get('setName') is None else 'replica set already initiated')"
