# Getting started with S.A.G.E.

## 1. Get access to Earth Engine

Open the [`hackathon-515400` project](https://console.cloud.google.com/home/dashboard?project=hackathon-515400) with the Google account you plan to use. If you need access, select **Request permissions** and, when available, choose **Send auto-generated email → Send request**. Ask the project administrator to grant your account the **Earth Engine Resource Writer** and **Service Usage Consumer** roles. [Requesting access](https://docs.cloud.google.com/iam/docs/request-missing-permissions) · [Earth Engine roles](https://developers.google.com/earth-engine/guides/access_control)

You can also email your access request to `szumaknikita@gmail.com`.

Or you can create your own Google Cloud project and enable the Earth Engine API.

## 2. Clone the repository and run the setup script

You need Git, Python, and a running Docker installation with Docker Compose. On Windows, use **Git Bash**.

```bash
git clone --branch main https://github.com/KungFuPepus/field-under-pressure-materials.git
cd field-under-pressure-materials
bash setup.sh
```

The script sets up Python and Earth Engine, verifies your credentials, and starts the dashboard, API, and MongoDB. If a browser opens, choose an account with access to the project and grant access to Google Drive. To switch accounts, run `bash setup.sh --relogin`.

Open the address printed by the script. The default is the [S.A.G.E. dashboard](http://127.0.0.1:5173). Select an orchard and choose **Analytics → Load field data**.
