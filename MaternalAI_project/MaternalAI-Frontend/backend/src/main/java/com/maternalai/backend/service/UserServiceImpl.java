package com.maternalai.backend.service;

import java.util.List;

import org.springframework.lang.NonNull;
import org.springframework.stereotype.Service;

import com.maternalai.backend.entity.User;
import com.maternalai.backend.repository.UserRepository;

@Service   // 🔥 MUST BE PRESENT
public class UserServiceImpl implements UserService {

    private final UserRepository userRepository;

    public UserServiceImpl(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

   

    @Override
    public List<User> getAllUsers() {
        return userRepository.findAll();
    }

    
    
    @Override
    public void deleteUser( @NonNull Long id) {
        if (userRepository.existsById(id)) {
            userRepository.deleteById(id);
        } else {
             throw new RuntimeException("User not found with id: " + id);
               }
    }
    
    @SuppressWarnings("null")
    @Override
public User updateUser(Long id, User user) {

    User existingUser = userRepository.findById(id)
            .orElseThrow(() -> new RuntimeException("User not found"));

    existingUser.setName(user.getName());
    existingUser.setEmail(user.getEmail());
    existingUser.setPassword(user.getPassword());

    return userRepository.save(existingUser);
}

@Override
public User saveUser(User user) {

    if(userRepository.existsByEmail(user.getEmail())) {
        throw new RuntimeException("Email already registered");
    }

    return userRepository.save(user);
}



@Override
public boolean login(String email, String password) {
    // TODO Auto-generated method stub
    
    User user = userRepository.findByEmail(email);
    return user != null &&
           user.getPassword() != null &&
           user.getPassword().equals(password);
}



@Override
public User getUserById(Long id) {
    // TODO Auto-generated method stub
    throw new UnsupportedOperationException("Unimplemented method 'getUserById'");
}
   



    
   

    

}