package com.aiassistant.core.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.os.PowerManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.aiassistant.core.MainActivity
import com.aiassistant.core.audio.AudioPipeline
import com.aiassistant.core.network.CameraStreamServer
import com.aiassistant.core.network.WebSocketClientManager
import kotlinx.coroutines.*
import timber.log.Timber
import java.util.concurrent.Executors

class AIServiceForegroundService : Service(), LifecycleOwner {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    
    private lateinit var lifecycleRegistry: LifecycleRegistry
    
    private lateinit var audioPipeline: AudioPipeline
    private lateinit var wsManager: WebSocketClientManager
    private val cameraServer = CameraStreamServer()
    
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate() {
        super.onCreate()
        lifecycleRegistry = LifecycleRegistry(this)
        lifecycleRegistry.currentState = Lifecycle.State.CREATED
        initManagers()
        startForegroundService()
    }

    override val lifecycle: Lifecycle
        get() = lifecycleRegistry

    private fun initManagers() {
        wsManager = WebSocketClientManager(
            serviceScope,
            onTextReceived = { msg ->
                ServiceEventBus.tryEmit(ServiceEvent.TextReceived(msg))
                Timber.d("Received text: ${msg.text}")
            },
            onAudioReceived = { audio ->
                audioPipeline.enqueuePlayback(audio)
            }
        )
        
        audioPipeline = AudioPipeline(serviceScope) { chunk ->
            wsManager.sendAudio(chunk)
        }

        serviceScope.launch {
            wsManager.connectionState.collect { state ->
                ServiceEventBus.emit(ServiceEvent.ConnectionStateChanged(state))
            }
        }
    }

    private fun startForegroundService() {
        lifecycleRegistry.currentState = Lifecycle.State.STARTED
        val channelId = "civicbot_service_channel"
        val channelName = "CivicBot Service"
        
        val channel = NotificationChannel(channelId, channelName, NotificationManager.IMPORTANCE_LOW)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("CivicBot Active")
            .setContentText("Streaming camera and audio...")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

        startForeground(1, notification)
        
        acquireWakeLock()
        startCapture()
    }

    private fun startCapture() {
        cameraServer.start()
        wsManager.connect()
        audioPipeline.startRecording()
        audioPipeline.initPlayback()
        
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
        audioManager.mode = android.media.AudioManager.MODE_IN_COMMUNICATION
        audioManager.isSpeakerphoneOn = com.aiassistant.core.config.ConfigManager.currentConfig.useSpeakerphone

        // Bind CameraX
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            imageAnalysis.setAnalyzer(cameraExecutor, cameraServer)
            
            try {
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    this,
                    if (com.aiassistant.core.config.ConfigManager.currentConfig.useFrontCamera) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA,
                    imageAnalysis
                )
            } catch (e: Exception) {
                Timber.e(e, "Camera binding failed")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun acquireWakeLock() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "AIAssistant:WakeLock")
        wakeLock?.acquire(300000L)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        lifecycleRegistry.currentState = Lifecycle.State.DESTROYED
        cameraServer.stop()
        wsManager.disconnect()
        audioPipeline.stopRecording()
        audioPipeline.stopPlayback()
        wakeLock?.release()
        serviceScope.cancel()
        cameraExecutor.shutdown()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
