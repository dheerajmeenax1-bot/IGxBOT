# IGxBOT

## Setup Instructions

1. Clone the repository:
   ```bash
   git clone https://github.com/dheerajmeenax1-bot/IGxBOT.git
   cd IGxBOT
   ```

2. Install the required dependencies:
   ```bash
   npm install
   ```

3. Create a `.env` file and set up your environment variables as specified in `.env.example`.

4. Run the application:
   ```bash
   npm start
   ```

## GitHub Actions Deployment Guide

To set up GitHub Actions for continuous deployment, follow these steps:

1. Create a new workflow file in the `.github/workflows` directory, for example `deploy.yml`.

2. Use the following configuration:
   ```yaml
   name: Deploy

   on:
     push:
       branches:
         - main

   jobs:
     deploy:
       runs-on: ubuntu-latest

       steps:
       - name: Checkout code
         uses: actions/checkout@v2

       - name: Setup Node.js
         uses: actions/setup-node@v2
         with:
           node-version: '14'

       - name: Install Dependencies
         run: |
           npm install

       - name: Build
         run: |
           npm run build

       - name: Deploy
         run: |
           npm run deploy
   ```

3. Make sure to add secrets in the repository settings if needed for deployment.

4. Push your changes to trigger the GitHub Actions workflow.