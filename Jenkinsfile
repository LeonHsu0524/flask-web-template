pipeline {
    agent any

    // ===== Build-time choices =====================================================
    // Pick these each time you click "Build with Parameters".
    parameters {
        choice(
            name: 'DEPLOY_TARGET',
            choices: ['prod-A', 'prod-B'],
            description: 'Which production computer to deploy to (see HOST_MAP below).'
        )
        choice(
            name: 'TEST_LEVEL',
            choices: ['smoke', 'health', 'full'],
            description: 'Which test phase(s) to run against staging.'
        )
        booleanParam(
            name: 'DEPLOY_PROD',
            defaultValue: false,
            description: 'Deploy to the selected production host after staging passes.'
        )
    }

    environment {
        // ===== Host map: name -> ssh target. Add machines here. =====
        HOST_MAP = "prod-A=deploy@CHANGE_ME_PROD_A_IP;prod-B=deploy@CHANGE_ME_PROD_B_IP"
        STAGING_URL = "http://localhost:5000"
    }

    stages {

        stage('Checkout Code') {
            steps { checkout scm }
        }

        stage('Build & Deploy to Staging') {
            steps {
                echo 'Building and starting staging containers...'
                sh 'docker compose down'
                sh 'docker compose up -d --build'
                echo 'Waiting for the app to boot...'
                sh 'sleep 10'
            }
        }

        stage('Test: Smoke') {
            when { expression { params.TEST_LEVEL in ['smoke', 'full'] } }
            steps {
                echo 'Running smoke tests...'
                sh 'docker compose exec -T flask-app python -m pytest -m smoke -q'
            }
        }

        stage('Test: Health') {
            when { expression { params.TEST_LEVEL in ['health', 'full'] } }
            steps {
                echo 'Running live health tests against staging...'
                sh "TARGET_URL=${STAGING_URL} python -m pytest -m health -q"
            }
        }

        stage('Test: Integration') {
            when { expression { params.TEST_LEVEL == 'full' } }
            steps {
                echo 'Running integration tests...'
                sh 'docker compose exec -T flask-app python -m pytest -m integration -q'
            }
        }

        stage('Shut Down Staging') {
            steps {
                echo 'Staging tests passed. Shutting down staging containers...'
                sh 'docker compose down'
            }
        }

        stage('Deploy to Production') {
            when {
                allOf {
                    expression { params.DEPLOY_PROD }
                    expression { env.GIT_BRANCH && env.GIT_BRANCH.contains('main') }
                }
            }
            steps {
                script {
                    // Resolve the chosen host from HOST_MAP.
                    def hosts = [:]
                    env.HOST_MAP.split(';').each { pair ->
                        def kv = pair.split('=')
                        hosts[kv[0]] = kv[1]
                    }
                    def target = hosts[params.DEPLOY_TARGET]
                    if (!target) { error "Unknown DEPLOY_TARGET: ${params.DEPLOY_TARGET}" }
                    echo "Deploying to ${params.DEPLOY_TARGET} (${target})..."

                    sh """
                        ssh -o StrictHostKeyChecking=no \
                            -o BatchMode=yes \
                            -o ConnectTimeout=10 \
                            ${target} "C:\\\\Windows\\\\System32\\\\wsl.exe -d Ubuntu -u root -e bash -c 'service docker start && cd /mnt/d/remoteWeb && git config --global --add safe.directory /mnt/d/remoteWeb && git fetch --all && git reset --hard origin/main && docker compose up -d --build'"
                    """
                }
            }
        }

        stage('Post-deploy Smoke') {
            when { expression { params.DEPLOY_PROD } }
            steps {
                echo 'Production deployed. (Add a post-deploy health check against the prod URL here.)'
            }
        }
    }

    post {
        always {
            sh 'docker image prune -f'
        }
    }
}
